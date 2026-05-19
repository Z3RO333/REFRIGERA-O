"""
Motor de automação inteligente de zonas térmicas.

Ciclo por zona:
  1. Coleta temperatura média das leituras atuais
  2. Classifica (COLD/COMFORT/WARM/HOT/CRITICAL)
  3. Valida regras de segurança (cooldown, limite diário, DND, status)
  4. Seleciona o AC mais influente da zona
  5. Calcula novo setpoint (±1°C)
  6. Registra decisão em zone_actions
  7. Executa se modo = auto | semi
  8. Após 12-15 min, verifica se a temperatura melhorou
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo
from app.config import settings

LOCAL_TZ = ZoneInfo(settings.app_timezone)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brise.client import brise_client
from app.cache.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.zone import ZoneAction, ZoneAutomation

logger = logging.getLogger(__name__)

# Statuses que impedem comandos
BLOCKED_STATUSES = {"SEM_LEITURA", "DESLIGADO", "COMPRESSOR_CYCLING"}

# Cooldown entre execuções na mesma zona (segundos)
ZONE_COOLDOWN_SECONDS = 900  # 15 min

# Janela de verificação: verifica ações com 12-18 min de vida
VERIFY_MIN_AGE_MINUTES = 12
VERIFY_MAX_AGE_MINUTES = 18

# Kill switch global — bloqueia toda automação imediatamente
KILL_SWITCH_KEY = "automation:kill_switch"


@dataclass
class ZoneConfig:
    key: str
    label: str
    sector_names: list[str]
    ideal_min: float
    ideal_max: float
    # ABERTA: área ampla; SALA_FECHADA: sala com paredes — sem interpolação térmica externa
    zone_type: str = "ABERTA"


# ── Zonas abertas (departamentos amplos) ──────────────────────────────────────
ZONES: dict[str, ZoneConfig] = {
    "convivencia":   ZoneConfig("convivencia",   "Convivência",            ["Convivência", "Refeitório", "Salas de Descanso"], 22, 24, "ABERTA"),
    "sac":           ZoneConfig("sac",           "SAC",                    ["SAC"],                                            22, 24, "ABERTA"),
    "conta-bemol":   ZoneConfig("conta-bemol",   "Conta Bemol",            ["Conta Bemol"],                                    22, 24, "ABERTA"),
    "auditorio":     ZoneConfig("auditorio",     "Auditório",              ["Auditório"],                                      22, 24, "ABERTA"),
    "comercial":     ZoneConfig("comercial",     "Comercial",              ["Comercial"],                                      22, 24, "ABERTA"),
    "marketing":     ZoneConfig("marketing",     "Marketing / Marketplace", ["Marketing", "Marketplace"],                      22, 24, "ABERTA"),
    "contabilidade": ZoneConfig("contabilidade", "Contabilidade / Risco",  ["Contabilidade", "Gestão de Risco"],               22, 24, "ABERTA"),
    "bemol-online":  ZoneConfig("bemol-online",  "Online / Televendas",    ["Bemol Online", "Televendas"],                    22, 24, "ABERTA"),
    "geral":         ZoneConfig("geral",         "Área central",           ["Geral", "Recepção", "CAB"],                      22, 24, "ABERTA"),
    "farmacia":      ZoneConfig("farmacia",      "Farmácia",               ["Farmácia"],                                      20, 22, "ABERTA"),
    "presidencia":   ZoneConfig("presidencia",   "Presidência",            ["Presidência"],                                   21, 25, "ABERTA"),
}


# ── Entrypoints do scheduler ──────────────────────────────────────────────────

async def run_zone_controller() -> None:
    """Avalia todas as zonas com automação ativa. Chamado pelo scheduler."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ZoneAutomation).where(
                ZoneAutomation.mode.not_in(["manual", "maintenance"])
            )
        )
        automations = result.scalars().all()

    if not automations:
        return

    logger.info("Zone controller: avaliando %d zonas ativas", len(automations))
    for automation in automations:
        try:
            await _evaluate_zone(automation)
        except Exception as exc:
            logger.error("Erro ao avaliar zona %s: %s", automation.zone_key, exc, exc_info=True)


async def run_zone_verification() -> None:
    """Verifica ações pendentes com 12-18 min de vida. Chamado pelo scheduler."""
    now = datetime.utcnow()
    min_age = now - timedelta(minutes=VERIFY_MAX_AGE_MINUTES)
    max_age = now - timedelta(minutes=VERIFY_MIN_AGE_MINUTES)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ZoneAction).where(
                ZoneAction.status == "pending_verification",
                ZoneAction.created_at >= min_age,
                ZoneAction.created_at <= max_age,
            )
        )
        pending = result.scalars().all()

        for action in pending:
            await _verify_action(action, session)

        # Ações que perderam a janela de verificação ficam presas como pending_verification;
        # marca como verified_failure para não poluir contadores diários e histórico.
        stale_result = await session.execute(
            select(ZoneAction).where(
                ZoneAction.status == "pending_verification",
                ZoneAction.created_at < min_age,
            )
        )
        stale = stale_result.scalars().all()
        for action in stale:
            action.status = "verified_failure"
            action.verified_at = now

        if pending or stale:
            await session.commit()
            if pending:
                logger.info("Zone verification: %d ações verificadas", len(pending))
            if stale:
                logger.warning("Zone verification: %d ações expiradas marcadas como falha", len(stale))


# ── Guardrails ────────────────────────────────────────────────────────────────

async def _check_guardrails(automation: ZoneAutomation) -> str | None:
    """Retorna motivo de bloqueio ou None se pode prosseguir."""
    # 1. Modo manutenção — bloqueia tudo; verifica expiração automática
    if automation.mode == "maintenance":
        if automation.blocked_until and datetime.utcnow() >= automation.blocked_until:
            # Prazo expirou: retorna automaticamente para manual
            automation.mode = "manual"
            automation.blocked_reason = None
            automation.blocked_until = None
            automation.blocked_by_user_name = None
            automation.blocked_at = None
            # Nota: o caller (run_zone_controller) não usa session aqui; essa limpeza
            # será persistida pelo _evaluate_zone que abre sua própria sessão.
        else:
            reason = automation.blocked_reason or "Zona em manutenção"
            if automation.blocked_until:
                reason += f" até {automation.blocked_until.strftime('%d/%m %H:%M')} UTC"
            return reason

    # 2. Kill switch global — para tudo imediatamente
    if await redis_client.exists(KILL_SWITCH_KEY):
        return "Kill switch global ativo — automação pausada"

    # 3. Zona crítica — bloqueia execução automática (auto/semi)
    if automation.is_critical_zone and automation.mode in ("auto", "semi"):
        return f"Zona marcada como crítica — modo '{automation.mode}' bloqueado"

    # 4. Janela de horário (sempre em horário de Manaus, UTC-4)
    now_manaus = datetime.now(tz=LOCAL_TZ)
    current_min = now_manaus.hour * 60 + now_manaus.minute
    start_min = automation.allowed_start_hour * 60 + automation.allowed_start_minute
    end_min   = automation.allowed_end_hour   * 60 + automation.allowed_end_minute
    if not (start_min <= current_min < end_min):
        sh, sm = automation.allowed_start_hour, automation.allowed_start_minute
        eh, em = automation.allowed_end_hour,   automation.allowed_end_minute
        return f"Fora do horário permitido ({sh:02d}:{sm:02d}–{eh:02d}:{em:02d}) — horário Manaus"

    return None


async def is_kill_switch_active() -> bool:
    return await redis_client.exists(KILL_SWITCH_KEY)


# ── Avaliação de uma zona ─────────────────────────────────────────────────────

async def _evaluate_zone(automation: ZoneAutomation) -> None:
    zone = ZONES.get(automation.zone_key)
    if not zone:
        return

    async with AsyncSessionLocal() as session:
        # ── Guardrails ────────────────────────────────────────────────────────
        guardrail_reason = await _check_guardrails(automation)
        if guardrail_reason:
            logger.debug("Zone %s bloqueada por guardrail: %s", automation.zone_key, guardrail_reason)
            return

        devices, params_map = await _get_zone_devices(automation.store_id, zone, session)

        readable = [
            d for d in devices
            if d.status.temperature is not None
            and d.device.status_latest
            and d.device.status_latest.status_classification not in BLOCKED_STATUSES
            and not d.device.dnd
            and not d.device.is_external_sensor  # sensores externos não recebem comandos
        ]

        if not readable:
            # SALA_FECHADA sem aparelho interno: registrar bloqueio explícito, não silenciar.
            # Aparelhos externos não podem compensar a sala por existir parede entre ambientes.
            if zone.zone_type == "SALA_FECHADA":
                await _log_blocked(
                    automation, zone, 0.0,
                    "SALA_FECHADA sem aparelho interno vinculado. "
                    "Automação não pode usar equipamento externo para corrigir temperatura "
                    "desta sala — verificação manual necessária.",
                    session,
                )
            return

        temps = [float(d.status.temperature) for d in readable]
        avg_temp = mean(temps)
        status = _classify(avg_temp, zone.ideal_min, zone.ideal_max)

        if status == "COMFORT":
            return

        # Cooldown — verificação rápida (leitura)
        cooldown_key = f"zone:cooldown:{automation.store_id}:{zone.key}"
        if await redis_client.exists(cooldown_key):
            return
        # Nota: o acquire_lock atômico acontece antes de executar (ver abaixo)

        # Limite diário
        today_count = await _daily_count(automation.store_id, zone.key, session)
        if today_count >= automation.max_daily_adjustments:
            await _log_blocked(
                automation, zone, avg_temp,
                f"Limite diário de {automation.max_daily_adjustments} ajustes atingido",
                session,
            )
            return

        # Falhas consecutivas (≥3 → alerta manutenção)
        if await _consecutive_failures(automation.store_id, zone.key, session) >= 3:
            await _raise_zone_alert(automation, zone, avg_temp, session)
            return

        # Seleciona melhor device
        best = _select_best_device(readable, status, params_map)
        if best is None:
            await _log_blocked(
                automation, zone, avg_temp,
                "Nenhum aparelho ajustável disponível na zona",
                session,
            )
            return

        best_device, best_params = best
        direction = "down" if status in ("WARM", "HOT", "CRITICAL") else "up"
        new_setpoint = best_params.setpoint_cool + (1 if direction == "up" else -1)

        if not (automation.setpoint_min <= new_setpoint <= automation.setpoint_max):
            await _log_blocked(
                automation, zone, avg_temp,
                f"Setpoint {new_setpoint}°C fora dos limites permitidos ({automation.setpoint_min}–{automation.setpoint_max}°C)",
                session,
            )
            return

        confidence = _confidence(avg_temp, zone, status, len(readable))
        reason = _build_reason(avg_temp, zone, status, best_device.device, direction)

        # Captura ANTES de _execute_setpoint modificar params.setpoint_cool
        setpoint_before = best_params.setpoint_cool

        action_status = "suggestion"
        block_reason = None

        if automation.mode in ("auto", "semi"):
            # acquire_lock é atômico (SET NX EX) — evita race entre múltiplos workers
            if not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                return  # outro worker chegou primeiro entre o exists() e agora
            ok = await _execute_setpoint(best_device.device, best_params, direction, automation, session)
            if ok:
                action_status = "pending_verification"
                logger.info(
                    "Zone %s [%s]: %s → setpoint %d→%d (conf=%.0f%%)",
                    zone.key, automation.mode, best_device.device.name,
                    setpoint_before, new_setpoint, confidence * 100,
                )
            else:
                action_status = "blocked"
                block_reason = "Falha ao enviar comando para a Brise API"
                await redis_client.release_lock(cooldown_key)  # libera para próxima tentativa

        action = ZoneAction(
            store_id=automation.store_id,
            zone_key=zone.key,
            zone_label=zone.label,
            device_id=best_device.device.id,
            device_name=best_device.device.name,
            direction=direction,
            temp_before=round(avg_temp, 2),
            ideal_min=zone.ideal_min,
            ideal_max=zone.ideal_max,
            setpoint_before=setpoint_before,
            setpoint_after=new_setpoint,
            reason=reason,
            confidence=confidence,
            mode=automation.mode,
            status=action_status,
            block_reason=block_reason,
        )
        session.add(action)
        await session.commit()


# ── Verificação de resultado ──────────────────────────────────────────────────

async def _verify_action(action: ZoneAction, session: AsyncSession) -> None:
    zone = ZONES.get(action.zone_key)
    if not zone:
        return

    devices, _ = await _get_zone_devices(action.store_id, zone, session)
    temps = [
        float(d.status.temperature)
        for d in devices
        if d.status.temperature is not None
    ]
    if not temps:
        return

    current_avg = mean(temps)
    action.temp_after = round(current_avg, 2)
    action.verified_at = datetime.utcnow()

    # Considera melhora se direção correta e ganho ≥ 0.3°C
    improved = False
    if action.direction == "down" and action.temp_before is not None:
        improved = current_avg <= action.temp_before - 0.3
    elif action.direction == "up" and action.temp_before is not None:
        improved = current_avg >= action.temp_before + 0.3

    action.status = "verified_success" if improved else "verified_failure"

    if not improved:
        failures = await _consecutive_failures(action.store_id, action.zone_key, session)
        if failures >= 3:
            await _raise_zone_alert(
                None, zone, current_avg, session,
                store_id=action.store_id,
                device_id=action.device_id,
            )

    logger.info(
        "Zone %s verification: %.1f°C → %.1f°C (%s)",
        action.zone_key,
        action.temp_before or 0,
        current_avg,
        action.status,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

class _DeviceRow:
    def __init__(self, device: Device, status: DeviceStatusLatest):
        self.device = device
        self.status = status


async def _get_zone_devices(
    store_id: uuid.UUID, zone: ZoneConfig, session: AsyncSession
) -> tuple[list[_DeviceRow], dict[uuid.UUID, DeviceParameters]]:
    from app.models.store import StoreSector
    result = await session.execute(
        select(Device, DeviceStatusLatest)
        .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .where(
            Device.active == True,
            StoreSector.store_id == store_id,
            StoreSector.name.in_(zone.sector_names),
        )
    )
    rows = result.all()
    devices = [_DeviceRow(d, s) for d, s in rows]

    # Fetch parameters
    if not devices:
        return [], {}
    device_ids = [r.device.id for r in devices]
    params_result = await session.execute(
        select(DeviceParameters).where(DeviceParameters.device_id.in_(device_ids))
    )
    params_map = {p.device_id: p for p in params_result.scalars().all()}
    return devices, params_map


def _select_best_device(
    readable: list[_DeviceRow],
    status: str,
    params_map: dict[uuid.UUID, DeviceParameters],
) -> tuple[_DeviceRow, DeviceParameters] | None:
    candidates = [
        r for r in readable
        if r.device.id in params_map and not r.device.source_url  # não é sensor externo
    ]
    if not candidates:
        return None

    # Ordena pelo maior delta_temp absoluto (mais fora de range = mais urgente)
    def sort_key(row: _DeviceRow) -> float:
        delta = row.status.delta_temp
        return abs(delta) if delta is not None else 0.0

    candidates.sort(key=sort_key, reverse=True)
    best = candidates[0]
    return best, params_map[best.device.id]


async def _execute_setpoint(
    device: Device,
    params: DeviceParameters,
    direction: str,
    automation: ZoneAutomation,
    session: AsyncSession,
) -> bool:
    new_setpoint = max(
        automation.setpoint_min,
        min(automation.setpoint_max, params.setpoint_cool + (1 if direction == "up" else -1)),
    )

    brise_params = {
        "modeDevice": 1,
        "modeAC": 0,
        "fanSpeed": params.fan_speed,
        "setpointCool": new_setpoint,
        "setpointHeat": params.setpoint_heat,
        "ecoCool": params.eco_cool,
        "ecoHeat": params.eco_heat,
    }

    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    if success:
        params.setpoint_cool = new_setpoint
        params.synced_at = datetime.utcnow()
        await session.commit()
    return success


async def _daily_count(store_id: uuid.UUID, zone_key: str, session: AsyncSession) -> int:
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(func.count(ZoneAction.id)).where(
            ZoneAction.store_id == store_id,
            ZoneAction.zone_key == zone_key,
            ZoneAction.status.in_(["pending_verification", "executed", "verified_success", "verified_failure"]),
            ZoneAction.created_at >= today,
        )
    )
    return result.scalar() or 0


async def _consecutive_failures(store_id: uuid.UUID, zone_key: str, session: AsyncSession) -> int:
    result = await session.execute(
        select(ZoneAction)
        .where(
            ZoneAction.store_id == store_id,
            ZoneAction.zone_key == zone_key,
            ZoneAction.status.in_(["verified_success", "verified_failure"]),
        )
        .order_by(ZoneAction.created_at.desc())
        .limit(5)
    )
    recent = result.scalars().all()
    count = 0
    for a in recent:
        if a.status == "verified_failure":
            count += 1
        else:
            break
    return count


async def _log_blocked(
    automation: ZoneAutomation,
    zone: ZoneConfig,
    avg_temp: float,
    reason: str,
    session: AsyncSession,
) -> None:
    session.add(ZoneAction(
        store_id=automation.store_id,
        zone_key=zone.key,
        zone_label=zone.label,
        temp_before=round(avg_temp, 2),
        ideal_min=zone.ideal_min,
        ideal_max=zone.ideal_max,
        reason=reason,
        mode=automation.mode,
        status="blocked",
        block_reason=reason,
        confidence=0.0,
    ))
    await session.commit()


async def _raise_zone_alert(
    automation: ZoneAutomation | None,
    zone: ZoneConfig,
    avg_temp: float,
    session: AsyncSession,
    store_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
) -> None:
    sid = store_id or (automation.store_id if automation else None)
    if sid is None:
        return
    if device_id is None and automation is not None:
        # Pega qualquer device da zona para associar o alerta
        from app.models.store import StoreSector
        res = await session.execute(
            select(Device.id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .where(StoreSector.store_id == sid, StoreSector.name.in_(zone.sector_names))
            .limit(1)
        )
        row = res.one_or_none()
        device_id = row[0] if row else None

    if device_id is None:
        return

    session.add(Alert(
        device_id=device_id,
        alert_type="ZONE_NOT_RESPONDING",
        severity="P2",
        status="OPEN",
        message=f"Zona {zone.label}: temperatura não melhora após 3 ajustes consecutivos — verificar filtros e carga térmica.",
        temperature_at_alert=avg_temp,
        opened_at=datetime.utcnow(),
    ))


def _classify(temp: float, ideal_min: float, ideal_max: float) -> str:
    if temp < ideal_min:       return "COLD"
    if temp <= ideal_max:      return "COMFORT"
    if temp <= ideal_max + 1.5: return "WARM"
    if temp <= ideal_max + 3.5: return "HOT"
    return "CRITICAL"


def _confidence(avg: float, zone: ZoneConfig, status: str, device_count: int) -> float:
    deviation = abs(avg - (zone.ideal_max if avg > zone.ideal_max else zone.ideal_min))
    dev_score = min(deviation / 3.0, 1.0)
    cnt_score = min(device_count / 3.0, 1.0)
    status_score = {"CRITICAL": 1.0, "HOT": 0.85, "WARM": 0.60, "COLD": 0.65}.get(status, 0.5)
    base = dev_score * 0.4 + cnt_score * 0.3 + status_score * 0.3
    # SALA_FECHADA com único aparelho: penalidade de confiança (sala isolada, poucos pontos)
    if zone.zone_type == "SALA_FECHADA" and device_count < 2:
        base *= 0.75
    return round(base, 2)


def _build_reason(
    avg: float,
    zone: ZoneConfig,
    status: str,
    device: Device,
    direction: str,
) -> str:
    direction_pt = "reduzir" if direction == "down" else "aumentar"
    labels = {"WARM": "zona aquecendo", "HOT": "zona quente", "CRITICAL": "zona crítica", "COLD": "zona fria"}
    label = labels.get(status, status)
    wall_note = (
        " [SALA_FECHADA — aparelho interno da sala usado. "
        "Influência de equipamentos externos ignorada por existir parede.]"
        if zone.zone_type == "SALA_FECHADA" else ""
    )
    return (
        f"Temperatura média {avg:.1f}°C ({label}). "
        f"Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ajuste via {device.name} para {direction_pt} 1°C no setpoint.{wall_note}"
    )


# ── API helper: obter automação (cria se não existir) ─────────────────────────

async def get_or_create_automation(
    store_id: uuid.UUID, zone_key: str, session: AsyncSession
) -> ZoneAutomation:
    result = await session.execute(
        select(ZoneAutomation).where(
            ZoneAutomation.store_id == store_id,
            ZoneAutomation.zone_key == zone_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    auto = ZoneAutomation(store_id=store_id, zone_key=zone_key)
    session.add(auto)
    await session.flush()
    return auto


async def get_zone_last_action(
    store_id: uuid.UUID, zone_key: str, session: AsyncSession
) -> ZoneAction | None:
    result = await session.execute(
        select(ZoneAction)
        .where(ZoneAction.store_id == store_id, ZoneAction.zone_key == zone_key)
        .order_by(ZoneAction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
