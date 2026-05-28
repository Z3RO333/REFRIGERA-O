"""
Motor de automação inteligente de zonas térmicas.

Ciclo por zona:
  1. Coleta temperatura média das leituras atuais
  2. Classifica (COLD/COMFORT/WARM/HOT/CRITICAL)
  3. Valida regras de segurança (cooldown, janela por device, DND, status)
  4. Seleciona o AC mais influente da zona
  5. Calcula novo setpoint (±1°C)
  6. Registra decisão em zone_actions
  7. Executa se modo = auto | semi
  8. Após 12-15 min, verifica se a temperatura melhorou
"""
import logging
import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo
from app.config import settings

LOCAL_TZ = ZoneInfo(settings.app_timezone)

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.brise.client import brise_client
from app.cache.device_cache import set_device_params
from app.cache.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.models.store import StoreSector
from app.models.zone import ZoneAction, ZoneAutomation
from app.services.thermal_spatial import DevicePoint, Hotspot, detect_hotspot, proximity_score
from app.services.learning_service import record_decision as _learning_record

logger = logging.getLogger(__name__)

# Statuses que impedem comandos
BLOCKED_STATUSES = {"SEM_LEITURA", "LEITURA_STALE", "AGUARDANDO_LEITURA", "DESLIGADO", "COMPRESSOR_CYCLING"}
THERMAL_OBSERVATION_BLOCKED_STATUSES = BLOCKED_STATUSES - {"DESLIGADO"}

# Cooldown entre execuções na mesma zona (segundos)
ZONE_COOLDOWN_SECONDS = 900  # 15 min

# Proteção por janela curta — evita rajadas sem bloquear o dia inteiro
DEVICE_WINDOW_SECONDS = 900      # janela de 15 min por device
DEVICE_WINDOW_MAX_CMDS = 4       # máximo de 4 comandos por device por janela

# Penalidades de ciclo curto. O controle por zona já evita rajadas; estes limites
# evitam economia agressiva que liga/desliga equipamento recém acionado.
MIN_ON_BEFORE_ECONOMY_OFF_MINUTES = 30
MIN_OFF_BEFORE_POWER_ON_MINUTES = 8

# Janela de verificação: verifica ações com 12-18 min de vida
VERIFY_MIN_AGE_MINUTES = 12
VERIFY_MAX_AGE_MINUTES = 18

# Kill switch global — bloqueia toda automação imediatamente
KILL_SWITCH_KEY = "automation:kill_switch"

# Janela anti-spam para sugestões iguais de IA/automação.
SUGGESTION_DEDUPE_SECONDS = 1800

# Gate de frescura: proporção mínima de leituras frescas para execução autônoma.
# Zonas com menos de 60 % de devices frescos não recebem comandos automáticos.
FRESHNESS_MIN_RATIO = 0.60


@dataclass
class ZoneConfig:
    key: str
    label: str
    sector_names: list[str]
    ideal_min: float
    ideal_max: float
    # ABERTA: área ampla; SALA_FECHADA: sala com paredes — sem interpolação térmica externa
    zone_type: str = "ABERTA"
    # Se definido, a zona usa IDs de device em vez de nomes de setor (zonas personalizadas)
    device_ids: list[uuid.UUID] | None = None


@dataclass
class EnergyCandidate:
    action: str
    row: object
    params: object
    thermal_impact_score: float
    energy_cost_score: float
    final_score: float
    reason: str
    setpoint_after: int | None = None


# ── Zonas abertas (departamentos amplos) ──────────────────────────────────────
# Zonas hardcoded removidas — sistema usa apenas zonas customizadas criadas pelo operador.
# Manter dict vazio para compatibilidade com código que ainda importa ZONES.
ZONES: dict[str, ZoneConfig] = {}


# ── Entrypoints do scheduler ──────────────────────────────────────────────────

async def run_zone_controller() -> None:
    """Avalia todas as zonas com automação ativa. Chamado pelo scheduler.

    Usa StoreSnapshot para carregar todos os dados em batch (4 queries por loja)
    em vez de N queries por zona. O snapshot já exclui devices com
    binding_mode='conflict_overlap', garantindo isolamento de conflito (P0.5).
    """
    from app.services.store_snapshot import build_snapshots_for_all_stores
    from app.services.store_epochs import get_all_epochs

    async with AsyncSessionLocal() as session:
        epoch_map = await get_all_epochs(session)
        snapshots = await build_snapshots_for_all_stores(session, epoch_map=epoch_map)
        result = await session.execute(
            select(ZoneAutomation).where(
                ZoneAutomation.mode.not_in(["manual", "maintenance"])
            )
        )
        automations = result.scalars().all()
        # Relê epochs após o snapshot para detectar bump_epoch disparado durante a construção
        current_epochs = await get_all_epochs(session)

    if not automations:
        return

    logger.info(
        "Zone controller: %d lojas, %d zonas ativas",
        len(snapshots), len(automations),
    )

    for automation in automations:
        snap = snapshots.get(automation.store_id)
        if snap is None:
            logger.warning(
                "Loja %s sem snapshot — ignorando zona %s",
                automation.store_id, automation.zone_key,
            )
            continue

        # Fencing token (P0.4): rejeita o plano se houve intervenção manual
        # entre o início do snapshot e agora (ex.: operador mudou modo noutro worker)
        if snap.epoch != current_epochs.get(automation.store_id, 0):
            logger.info(
                "Zone %s: epoch mudou (%d → %d) — plano descartado",
                automation.zone_key,
                snap.epoch,
                current_epochs.get(automation.store_id, 0),
            )
            continue

        zone_snap = snap.zones.get(automation.zone_key)
        if zone_snap is None:
            logger.warning("Zona '%s' sem configuração no snapshot — ignorando", automation.zone_key)
            continue

        # Gate de frescura (P0.2): bloqueia execução autônoma quando dados obsoletos demais.
        # Somente aplica quando há devices com temperatura — zona sem leitura nenhuma
        # é tratada normalmente pelo diagnóstico interno de _evaluate_zone.
        if (automation.mode in ("auto", "semi")
                and zone_snap.total_with_temp > 0
                and zone_snap.freshness_ratio < FRESHNESS_MIN_RATIO):
            logger.info(
                "Zone %s: freshness %.0f%% < %.0f%% — execução autônoma bloqueada (dados obsoletos)",
                automation.zone_key,
                zone_snap.freshness_ratio * 100,
                FRESHNESS_MIN_RATIO * 100,
            )
            continue

        # ZoneConfig a partir do snapshot — device_ids já excluem conflict_overlap (P0.5)
        zone = ZoneConfig(
            key=zone_snap.zone_key,
            label=zone_snap.name,
            sector_names=[],
            ideal_min=zone_snap.ideal_min,
            ideal_max=zone_snap.ideal_max,
            zone_type=zone_snap.zone_type,
            device_ids=list(zone_snap.device_ids),
        )

        try:
            await _evaluate_zone(automation, zone_override=zone)
        except Exception as exc:
            logger.error("Erro ao avaliar zona %s: %s", automation.zone_key, exc, exc_info=True)


async def release_expired_maintenance_zones() -> None:
    """Bug 2: libera automaticamente zonas em manutenção com blocked_until expirado."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ZoneAutomation).where(
                ZoneAutomation.mode == "maintenance",
                ZoneAutomation.blocked_until.is_not(None),
                ZoneAutomation.blocked_until <= now,
            )
        )
        expired = result.scalars().all()
        for auto in expired:
            logger.info("Liberando manutenção expirada: zona %s (expirou %s)", auto.zone_key, auto.blocked_until)
            auto.mode = "manual"
            auto.blocked_reason = None
            auto.blocked_until = None
            auto.blocked_by_user_name = None
            auto.blocked_at = None
        if expired:
            await session.commit()
            logger.info("release_expired_maintenance_zones: %d zonas liberadas", len(expired))


async def _load_all_custom_zones(session: AsyncSession) -> dict[str, ZoneConfig]:
    """Carrega todas as zonas personalizadas do banco em uma única query."""
    from app.models.custom_zone import CustomZone, CustomZoneDevice
    result = await session.execute(
        select(
            CustomZone.zone_key, CustomZone.name,
            CustomZone.ideal_min, CustomZone.ideal_max, CustomZone.zone_type,
            CustomZoneDevice.device_id,
        ).outerjoin(CustomZoneDevice, CustomZone.id == CustomZoneDevice.zone_id)
        .where(CustomZone.active == True)
    )
    zones: dict[str, ZoneConfig] = {}
    for zone_key, name, ideal_min, ideal_max, zone_type, dev_id in result.all():
        if zone_key not in zones:
            zones[zone_key] = ZoneConfig(
                key=zone_key, label=name, sector_names=[],
                ideal_min=ideal_min, ideal_max=ideal_max,
                zone_type=zone_type, device_ids=[],
            )
        if dev_id is not None:
            zones[zone_key].device_ids.append(dev_id)  # type: ignore[union-attr]
    return zones


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
            # Prazo expirou: persiste a limpeza diretamente no banco com sessão própria
            async with AsyncSessionLocal() as fix_session:
                await fix_session.execute(
                    update(ZoneAutomation)
                    .where(ZoneAutomation.id == automation.id)
                    .values(
                        mode="manual",
                        blocked_reason=None,
                        blocked_until=None,
                        blocked_by_user_name=None,
                        blocked_at=None,
                    )
                )
                await fix_session.commit()
            automation.mode = "manual"
            automation.blocked_reason = None
            automation.blocked_until = None
            automation.blocked_by_user_name = None
            automation.blocked_at = None
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


# ── Tendência térmica rápida ──────────────────────────────────────────────────

async def _quick_trend(
    store_id: uuid.UUID,
    zone: ZoneConfig,
    session: AsyncSession,
    window_minutes: int = 30,
) -> float | None:
    """OLS slope (°C/hora) dos últimos `window_minutes` para a zona. None se dados insuficientes."""
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=window_minutes)

    if zone.device_ids is not None:
        device_ids = [d for d in zone.device_ids]
    else:
        dev_result = await session.execute(
            select(Device.id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .where(
                Device.active == True,
                StoreSector.store_id == store_id,
                StoreSector.name.in_(zone.sector_names),
                Device.source_url.is_(None),
            )
        )
        device_ids = [row[0] for row in dev_result.all()]
    if not device_ids:
        return None

    hist = await session.execute(
        select(DeviceReading.time, DeviceReading.temperature)
        .where(
            DeviceReading.device_id.in_(device_ids),
            DeviceReading.time >= cutoff,
            DeviceReading.temperature.is_not(None),
        )
        .order_by(DeviceReading.time.asc())
    )
    hist_rows = hist.all()
    if len(hist_rows) < 3:
        return None

    buckets: dict[int, list[float]] = {}
    for t_row, temp in hist_rows:
        b = int((t_row - cutoff).total_seconds() / 300)
        buckets.setdefault(b, []).append(float(temp))

    points = sorted([(b * 5.0, mean(ts)) for b, ts in buckets.items()])
    if len(points) < 2:
        return None

    n = len(points)
    sx  = sum(x for x, _ in points)
    sy  = sum(y for _, y in points)
    sxy = sum(x * y for x, y in points)
    sx2 = sum(x * x for x, _ in points)
    denom = n * sx2 - sx * sx
    if abs(denom) < 1e-9:
        return None
    return round((n * sxy - sx * sy) / denom * 60, 2)


def _step_size(status: str) -> int:
    """Passo conservador: automação sempre altera 1°C por ciclo."""
    return 1


# Fan speed adaptativo por status da zona
# 1=baixo  2=médio  3=alto  4=turbo
_FAN_SPEED_BY_STATUS: dict[str, int] = {
    "CRITICAL": 4,
    "HOT":      3,
    "WARM":     2,
    "COMFORT":  2,
    "COLD":     1,
    "NO_READING": 2,
}


def _target_fan_speed(status: str, current_fan_speed: int | None = None) -> int:
    """Retorna a velocidade de fan adequada para o status térmico da zona.

    Nunca reduz abaixo do atual se a zona estiver aquecendo — evita piorar
    uma situação crítica por fan speed insuficiente.
    """
    target = _FAN_SPEED_BY_STATUS.get(status, 2)
    if current_fan_speed is not None and status in ("WARM", "HOT", "CRITICAL"):
        return max(target, current_fan_speed)
    return target


async def _log_trending(
    automation: ZoneAutomation,
    zone: ZoneConfig,
    avg_temp: float,
    trend: float,
    session: AsyncSession,
) -> None:
    """Registra suggestion quando zona está confortável mas aquecendo rapidamente."""
    cooldown_key = f"zone:trend_suggestion:{automation.store_id}:{zone.key}"
    if await redis_client.exists(cooldown_key):
        return
    await redis_client.set(cooldown_key, "1", ttl=1800)  # cooldown de 30 min para sugestões de tendência

    minutes_to_warm = int((zone.ideal_max - avg_temp) / trend * 60) if trend > 0 else 0
    session.add(ZoneAction(
        store_id=automation.store_id,
        zone_key=zone.key,
        zone_label=zone.label,
        temp_before=round(avg_temp, 2),
        ideal_min=zone.ideal_min,
        ideal_max=zone.ideal_max,
        direction="down",
        reason=(
            f"Zona confortável ({avg_temp:.1f}°C) mas aquecendo a {trend:+.1f}°C/h. "
            f"Previsão: exceder faixa ideal em ~{minutes_to_warm} min. Monitorar."
        ),
        confidence=round(min(trend / 4.0, 1.0), 2),
        mode=automation.mode,
        status="suggestion",
    ))
    await session.commit()

    await redis_client.publish("zone.action.created", {
        "store_id": str(automation.store_id),
        "zone_key": zone.key,
        "zone_label": zone.label,
        "status": "suggestion",
        "reason": "trending_warm",
        "trend_c_per_hour": trend,
    })


async def _log_energy_saving_suggestion(
    automation: ZoneAutomation,
    zone: ZoneConfig,
    avg_temp: float,
    reason: str,
    energy_payload: dict,
    session: AsyncSession,
) -> None:
    """Registra oportunidade de economia quando a zona já está confortável."""
    cooldown_key = f"zone:energy_suggestion:{automation.store_id}:{zone.key}"
    if await redis_client.exists(cooldown_key):
        return
    await redis_client.set(cooldown_key, "1", ttl=1800)

    full_reason = _append_energy_decision(
        reason + " Zona confortável: não reduzir setpoint nem ligar aparelho adicional.",
        energy_payload,
    )
    action = ZoneAction(
        store_id=automation.store_id,
        zone_key=zone.key,
        zone_label=zone.label,
        temp_before=round(avg_temp, 2),
        ideal_min=zone.ideal_min,
        ideal_max=zone.ideal_max,
        direction="up",
        reason=full_reason,
        confidence=0.72,
        mode=automation.mode,
        status="suggestion",
        suggestion_signature=_suggestion_signature(
            zone=zone,
            hotspot=None,
            issue_type="energy_waste",
            action_type="economy_review",
            target_devices=[],
            severity="COMFORT",
        ),
    )
    _, deduped = await _save_zone_action(action, session)
    if deduped:
        return

    await redis_client.publish("zone.action.created", {
        "store_id": str(automation.store_id),
        "zone_key": zone.key,
        "zone_label": zone.label,
        "direction": "up",
        "status": "suggestion",
        "confidence": 72,
        "action": "economy_review",
        "energy_strategy": energy_payload.get("energy_strategy"),
        "energy_decision": energy_payload,
    })


# ── Avaliação de uma zona ─────────────────────────────────────────────────────

async def _evaluate_zone(automation: ZoneAutomation, zone_override: ZoneConfig | None = None) -> None:
    zone = zone_override or ZONES.get(automation.zone_key)
    if not zone:
        return

    async with AsyncSessionLocal() as session:
        # ── Guardrails ────────────────────────────────────────────────────────
        guardrail_reason = await _check_guardrails(automation)
        if guardrail_reason:
            logger.debug("Zone %s bloqueada por guardrail: %s", automation.zone_key, guardrail_reason)
            return

        _t0 = time.monotonic()
        devices, params_map = await _get_zone_devices(automation.store_id, zone, session)
        await _sync_zone_parameters_from_brise(devices, params_map, session)

        # Fontes de temperatura: ACs ativos + sensores externos + ACs desligados que
        # ainda reportam temperatura. DESLIGADO observa o hotspot, mas nao recebe setpoint.
        temp_sources = [d for d in devices if _is_thermal_observation_source(d)]

        # Ajustáveis via comando: apenas ACs ligados/comunicando. AC desligado com
        # leitura alimenta a decisao espacial e deve ser tratado por power_on.
        readable = [d for d in temp_sources if _is_setpoint_readable_source(d)]

        if not temp_sources:
            # Sem leitura térmica disponível — diagnóstico detalhado com rate-limit anti-spam
            ac_devices = [d for d in devices if not d.device.source_url and not d.device.dnd]
            n_total = len(ac_devices)
            n_off = sum(1 for d in ac_devices if d.status.status_classification == "DESLIGADO")
            n_waiting = sum(1 for d in ac_devices if d.status.status_classification == "AGUARDANDO_LEITURA")
            n_no_comm = sum(1 for d in ac_devices if d.status.status_classification in {"SEM_LEITURA", "LEITURA_STALE"})
            n_cycling = sum(1 for d in ac_devices if d.status.status_classification == "COMPRESSOR_CYCLING")

            if n_total == 0:
                diag = "Zona sem aparelhos vinculados — impossível controlar temperatura automaticamente."
            elif n_off == n_total:
                diag = (
                    f"{n_total} AC(s) vinculado(s), todos desligados — sem leitura térmica disponível. "
                    "Ligue manualmente pelo menos um AC para iniciar a automação."
                )
            elif n_waiting > 0 and n_off + n_waiting == n_total:
                diag = (
                    f"{n_total} AC(s) vinculado(s): {n_waiting} aguardando primeira leitura após ligar"
                    + (f", {n_off} desligado(s)" if n_off else "") + "."
                )
            elif n_no_comm > 0:
                diag = (
                    f"{n_total} AC(s) vinculado(s): {n_no_comm} sem comunicação com a Brise API"
                    + (f", {n_off} desligado(s)" if n_off else "")
                    + ". Verifique conectividade dos equipamentos."
                )
            elif n_cycling > 0:
                diag = (
                    f"{n_total} AC(s) vinculado(s): {n_cycling} com ciclo de compressor — aguardando normalização."
                )
            else:
                diag = f"{n_total} AC(s) vinculado(s) sem leitura térmica disponível neste momento."

            if zone.zone_type == "SALA_FECHADA":
                await _log_blocked(automation, zone, 0.0, diag, session)
            elif n_total > 0:
                # ABERTA: só loga uma vez a cada 30 min para não poluir histórico
                diag_key = f"zone:no_reading_log:{automation.store_id}:{zone.key}"
                if not await redis_client.exists(diag_key):
                    await redis_client.set(diag_key, "1", ttl=1800)
                    await _log_blocked(automation, zone, 0.0, diag, session)
            return

        temps = [float(d.status.temperature) for d in temp_sources]
        avg_temp = mean(temps)
        status = _classify(avg_temp, zone.ideal_min, zone.ideal_max)

        # Detecção de hotspot espacial — None se zona uniforme ou sem coordenadas
        _spatial_points = [
            DevicePoint(
                device_id=str(d.device.id),
                device_name=d.device.name or "",
                pos_x=d.device.position_x,
                pos_y=d.device.position_y,
                influence_radius_m=float(d.device.influence_radius_m or 8),
                temperature=float(d.status.temperature),
                is_on=d.status.state is True,
                is_off=d.status.state is False,
                is_available=True,
                btu=d.device.btu or 0,
            )
            for d in temp_sources
        ]
        hotspot = detect_hotspot(_spatial_points)

        # Tendência térmica (últimos 30 min)
        trend = await _quick_trend(automation.store_id, zone, session)
        energy_strategy = _energy_strategy(automation)

        if status == "COMFORT":
            local_status = _local_hotspot_status(hotspot, zone)
            if local_status is not None:
                # Média confortável, mas existe uma subárea acima da faixa ideal.
                # Ação permitida: ligar capacidade disponível perto do hotspot.
                # Evita redução agressiva de setpoint quando a zona toda ainda está verde.
                if trend is not None and trend < -1.5:
                    logger.debug(
                        "Zone %s: hotspot local %.1f°C, mas zona resfriando a %.1f°C/h — aguardando",
                        zone.key, hotspot.peak_temp, trend,
                    )
                    return

                cooldown_key = f"zone:cooldown:{automation.store_id}:{zone.key}"
                if await redis_client.exists(cooldown_key):
                    return
                if await _consecutive_failures(automation.store_id, zone.key, session) >= 3:
                    await _raise_zone_alert(automation, zone, avg_temp, session)
                    return

                power_candidates = _build_power_on_candidates(
                    devices, params_map, hotspot=hotspot, strategy=energy_strategy
                )
                power_on_candidate = (
                    (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
                )
                if power_on_candidate is not None:
                    power_device, power_params = power_on_candidate
                    confidence = _confidence(hotspot.peak_temp, zone, local_status, max(len(readable), 1))
                    power_setpoint = _power_on_setpoint(power_params, zone, automation, local_status)
                    energy_payload = _energy_decision_payload(
                        zone=zone,
                        status="hotspot",
                        strategy=energy_strategy,
                        avg_temp=avg_temp,
                        devices=devices,
                        params_map=params_map,
                        selected=power_candidates[0],
                        candidates=power_candidates,
                    )
                    reason = _build_local_hotspot_power_on_reason(
                        avg_temp, zone, local_status, power_device.device, trend, hotspot
                    )
                    reason = _append_energy_decision(reason, energy_payload)
                    setpoint_before = power_params.setpoint_cool
                    action_status = "suggestion"
                    block_reason = None
                    _api_ms: int | None = None

                    if automation.mode in ("auto", "semi"):
                        if not await _device_window_ok(power_device.device.id):
                            action_status = "blocked"
                            block_reason = (
                                f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                                f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                                f"{power_device.device.name}"
                            )
                        elif not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                            return
                        else:
                            ok, _api_ms = await _execute_power_on(
                                power_device.device, power_params, session,
                                target_setpoint=power_setpoint, zone_status=status,
                            )
                            if ok:
                                action_status = "pending_verification"
                                logger.info(
                                    "Zone %s [%s]: ligando %s por hotspot local %.1f°C (média %.1f°C)",
                                    zone.key, automation.mode, power_device.device.name,
                                    hotspot.peak_temp, avg_temp,
                                )
                            else:
                                action_status = "blocked"
                                block_reason = "Falha ao ligar aparelho pela Brise API"
                                await redis_client.release_lock(cooldown_key)

                    action = ZoneAction(
                        store_id=automation.store_id,
                        zone_key=zone.key,
                        zone_label=zone.label,
                        device_id=power_device.device.id,
                        device_name=power_device.device.name,
                        direction="down",
                        temp_before=round(avg_temp, 2),
                        ideal_min=zone.ideal_min,
                        ideal_max=zone.ideal_max,
                        setpoint_before=setpoint_before,
                        setpoint_after=power_setpoint,
                        reason=reason,
                        confidence=confidence,
                        mode=automation.mode,
                        status=action_status,
                        block_reason=block_reason,
                        decision_ms=int((time.monotonic() - _t0) * 1000),
                        api_ms=_api_ms,
                        suggestion_signature=(
                            _suggestion_signature(
                                zone=zone,
                                hotspot=hotspot,
                                issue_type="local_hotspot",
                                action_type="power_on",
                                target_devices=[power_device.device.id],
                                severity=local_status,
                            )
                            if action_status == "suggestion" else None
                        ),
                    )
                    _, deduped = await _save_zone_action(action, session)
                    if deduped:
                        return

                    await redis_client.publish("zone.action.created", {
                        "store_id": str(automation.store_id),
                        "zone_key": zone.key,
                        "zone_label": zone.label,
                        "device_name": power_device.device.name,
                        "direction": "down",
                        "status": action_status,
                        "confidence": round(confidence * 100),
                        "setpoint_before": setpoint_before,
                        "setpoint_after": power_setpoint,
                        "action": "power_on",
                        "energy_strategy": energy_strategy,
                        "energy_decision": energy_payload,
                        "local_hotspot": True,
                        "hotspot_temp": hotspot.peak_temp,
                    })
                    return

                scored_setpoint_candidates = _build_setpoint_candidates(
                    readable,
                    params_map,
                    direction="down",
                    setpoint_min=automation.setpoint_min,
                    setpoint_max=automation.setpoint_max,
                    hotspot=hotspot,
                    zone=zone,
                    automation=automation,
                    status=local_status,
                    strategy=energy_strategy,
                )
                setpoint_candidates = [
                    (candidate.row, candidate.params) for candidate in scored_setpoint_candidates
                ]
                if setpoint_candidates:
                    best_device, best_params = setpoint_candidates[0]
                    setpoint_before = best_params.setpoint_cool
                    new_setpoint = scored_setpoint_candidates[0].setpoint_after
                    if new_setpoint == setpoint_before:
                        await _log_local_hotspot_suggestion(
                            automation, zone, avg_temp, local_status, trend, hotspot, session,
                            no_adjustable_reason="aparelhos próximos já estão ligados, mas sem margem útil de setpoint",
                        )
                        return

                    confidence = _confidence(hotspot.peak_temp, zone, local_status, max(len(readable), 1))
                    energy_payload = _energy_decision_payload(
                        zone=zone,
                        status="hotspot",
                        strategy=energy_strategy,
                        avg_temp=avg_temp,
                        devices=devices,
                        params_map=params_map,
                        selected=scored_setpoint_candidates[0],
                        candidates=scored_setpoint_candidates,
                    )
                    reason = _build_local_hotspot_setpoint_reason(
                        avg_temp,
                        zone,
                        local_status,
                        best_device.device,
                        setpoint_before,
                        new_setpoint,
                        trend,
                        hotspot,
                        [row.device.name for row, _ in setpoint_candidates[:3]],
                    )
                    reason = _append_energy_decision(reason, energy_payload)
                    action_status = "suggestion"
                    block_reason = None
                    _api_ms: int | None = None

                    if automation.mode in ("auto", "semi"):
                        if not await _device_window_ok(best_device.device.id):
                            action_status = "blocked"
                            block_reason = (
                                f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                                f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                                f"{best_device.device.name}"
                            )
                        elif not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                            return
                        else:
                            ok, _api_ms = await _execute_setpoint(
                                best_device.device, best_params, "down", automation, session,
                                step=1, zone_status=status,
                            )
                            if ok:
                                action_status = "pending_verification"
                                logger.info(
                                    "Zone %s [%s]: hotspot local %.1f°C, ajustando %s setpoint %d→%d",
                                    zone.key, automation.mode, hotspot.peak_temp,
                                    best_device.device.name, setpoint_before, new_setpoint,
                                )
                            else:
                                action_status = "blocked"
                                block_reason = "Falha ao enviar comando para a Brise API"
                                await redis_client.release_lock(cooldown_key)

                    action = ZoneAction(
                        store_id=automation.store_id,
                        zone_key=zone.key,
                        zone_label=zone.label,
                        device_id=best_device.device.id,
                        device_name=best_device.device.name,
                        direction="down",
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
                        decision_ms=int((time.monotonic() - _t0) * 1000),
                        api_ms=_api_ms,
                        suggestion_signature=(
                            _suggestion_signature(
                                zone=zone,
                                hotspot=hotspot,
                                issue_type="local_hotspot",
                                action_type="set_temperature",
                                target_devices=[best_device.device.id],
                                severity=local_status,
                                setpoint_after=new_setpoint,
                            )
                            if action_status == "suggestion" else None
                        ),
                    )
                    _, deduped = await _save_zone_action(action, session)
                    if deduped:
                        return

                    await redis_client.publish("zone.action.created", {
                        "store_id": str(automation.store_id),
                        "zone_key": zone.key,
                        "zone_label": zone.label,
                        "device_name": best_device.device.name,
                        "direction": "down",
                        "status": action_status,
                        "confidence": round(confidence * 100),
                        "setpoint_before": setpoint_before,
                        "setpoint_after": new_setpoint,
                        "action": "set_temperature",
                        "energy_strategy": energy_strategy,
                        "energy_decision": energy_payload,
                        "local_hotspot": True,
                        "hotspot_temp": hotspot.peak_temp,
                    })
                    return

                await _log_local_hotspot_suggestion(automation, zone, avg_temp, local_status, trend, hotspot, session)
                return

            # Zona confortável mas aquecendo rapidamente → suggestion preemptiva
            if trend is not None and trend > 2.5:
                await _log_trending(automation, zone, avg_temp, trend, session)
                return
            waste, waste_reason = _zone_energy_waste(devices, params_map, zone, avg_temp, trend)
            if waste:
                payload = _energy_decision_payload(
                    zone=zone,
                    status="comfortable",
                    strategy=energy_strategy,
                    avg_temp=avg_temp,
                    devices=devices,
                    params_map=params_map,
                    selected=None,
                    candidates=[],
                )
                await _log_energy_saving_suggestion(
                    automation, zone, avg_temp, waste_reason, payload, session
                )
            return

        # Zona WARM mas já resfriando — dar tempo ao AC anterior de responder
        if status == "WARM" and trend is not None and trend < -1.5:
            logger.debug("Zone %s: WARM mas resfriando a %.1f°C/h — aguardando resposta", zone.key, trend)
            return

        # Cooldown — verificação rápida (leitura)
        cooldown_key = f"zone:cooldown:{automation.store_id}:{zone.key}"
        if await redis_client.exists(cooldown_key):
            return
        # Nota: o acquire_lock atômico acontece antes de executar (ver abaixo)

        # Falhas consecutivas (≥3 → alerta manutenção)
        if await _consecutive_failures(automation.store_id, zone.key, session) >= 3:
            await _raise_zone_alert(automation, zone, avg_temp, session)
            return

        direction = "down" if status in ("WARM", "HOT", "CRITICAL") else "up"
        step = _step_size(status)

        power_candidates = (
            _build_power_on_candidates(devices, params_map, hotspot=hotspot, strategy=energy_strategy)
            if direction == "down" else []
        )
        power_on_candidate = (
            (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
        )
        if power_on_candidate is not None:
            power_device, power_params = power_on_candidate
            confidence = _confidence(avg_temp, zone, status, max(len(readable), 1))
            power_setpoint = _power_on_setpoint(power_params, zone, automation, status)
            energy_payload = _energy_decision_payload(
                zone=zone,
                status=status,
                strategy=energy_strategy,
                avg_temp=avg_temp,
                devices=devices,
                params_map=params_map,
                selected=power_candidates[0],
                candidates=power_candidates,
            )
            reason = _build_power_on_reason(avg_temp, zone, status, power_device.device, trend, hotspot=hotspot)
            reason = _append_energy_decision(reason, energy_payload)
            setpoint_before = power_params.setpoint_cool
            action_status = "suggestion"
            block_reason = None
            _api_ms: int | None = None

            if automation.mode in ("auto", "semi"):
                if not await _device_window_ok(power_device.device.id):
                    action_status = "blocked"
                    block_reason = (
                        f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                        f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                        f"{power_device.device.name}"
                    )
                elif not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                    return
                else:
                    ok, _api_ms = await _execute_power_on(
                        power_device.device, power_params, session,
                        target_setpoint=power_setpoint, zone_status=status,
                    )
                    if ok:
                        action_status = "pending_verification"
                        logger.info(
                            "Zone %s [%s]: ligando %s para resfriar zona (conf=%.0f%%)",
                            zone.key, automation.mode, power_device.device.name, confidence * 100,
                        )
                    else:
                        action_status = "blocked"
                        block_reason = "Falha ao ligar aparelho pela Brise API"
                        await redis_client.release_lock(cooldown_key)

            _power_api_ms = _api_ms
            action = ZoneAction(
                store_id=automation.store_id,
                zone_key=zone.key,
                zone_label=zone.label,
                device_id=power_device.device.id,
                device_name=power_device.device.name,
                direction="down",
                temp_before=round(avg_temp, 2),
                ideal_min=zone.ideal_min,
                ideal_max=zone.ideal_max,
                setpoint_before=setpoint_before,
                setpoint_after=power_setpoint,
                reason=reason,
                confidence=confidence,
                mode=automation.mode,
                status=action_status,
                block_reason=block_reason,
                decision_ms=int((time.monotonic() - _t0) * 1000),
                api_ms=_power_api_ms,
            )
            session.add(action)
            await session.commit()
            try:
                _pc = power_candidates[0]
                await _learning_record(
                    session=session,
                    zone_action_id=action.id,
                    store_id=automation.store_id,
                    zone_key=zone.key,
                    zone_label=zone.label,
                    decision_type="auto" if action_status == "pending_verification" else "suggestion",
                    thermal_status=status,
                    avg_temp=round(avg_temp, 2),
                    ideal_min=zone.ideal_min,
                    ideal_max=zone.ideal_max,
                    trend_c_per_hour=trend,
                    freshness_ratio=None,
                    devices_on=sum(1 for r in devices if _device_is_on(r, params_map.get(r.device.id))),
                    devices_off=sum(1 for r in devices if _device_is_off(r, params_map.get(r.device.id))),
                    had_hotspot=hotspot is not None,
                    hotspot_peak_temp=hotspot.peak_temp if hotspot else None,
                    action_type="power_on",
                    device_id=power_device.device.id,
                    device_name=power_device.device.name,
                    setpoint_from=setpoint_before,
                    setpoint_to=power_setpoint,
                    fan_speed_from=power_params.fan_speed,
                    fan_speed_to=None,
                    confidence=confidence,
                    energy_strategy=energy_strategy,
                    thermal_impact_score=_pc.thermal_impact_score,
                    energy_cost_score=_pc.energy_cost_score,
                    final_score=_pc.final_score,
                )
                await session.commit()
            except Exception as _le:
                logger.warning("learning record falhou (power_on): %s", _le)

            if action_status == "pending_verification" and _power_api_ms is not None:
                logger.info(
                    "Zone %s: decisão em %dms, API em %dms",
                    zone.key,
                    int((time.monotonic() - _t0) * 1000),
                    _power_api_ms,
                )

            await redis_client.publish("zone.action.created", {
                "store_id": str(automation.store_id),
                "zone_key": zone.key,
                "zone_label": zone.label,
                "device_name": power_device.device.name,
                "direction": "down",
                "status": action_status,
                "confidence": round(confidence * 100),
                "setpoint_before": setpoint_before,
                "setpoint_after": power_setpoint,
                "action": "power_on",
                "energy_strategy": energy_strategy,
                "energy_decision": energy_payload,
            })
            return

        # Seleciona melhor device (com verificação de headroom de setpoint)
        scored_setpoint_candidates = _build_setpoint_candidates(
            readable,
            params_map,
            direction=direction,
            setpoint_min=automation.setpoint_min,
            setpoint_max=automation.setpoint_max,
            hotspot=hotspot,
            zone=zone,
            automation=automation,
            status=status,
            strategy=energy_strategy,
        )
        best = (
            (scored_setpoint_candidates[0].row, scored_setpoint_candidates[0].params)
            if scored_setpoint_candidates else None
        )
        if best is None:
            # Zona fria com todos os ACs no setpoint_max → tentar desligar o AC
            # em vez de apenas bloquear: AC no máximo mas zona ainda fria = ineficaz.
            if direction == "up":
                await _try_power_off_cold_zone(
                    automation, zone, devices, params_map, avg_temp, trend, status,
                    energy_strategy, hotspot, _t0, session,
                )
                return
            reason = _build_no_adjustable_reason(
                readable, devices, params_map, direction,
                automation.setpoint_min, automation.setpoint_max, zone,
            )
            await _log_blocked(automation, zone, avg_temp, reason, session)
            return

        best_device, best_params = best
        new_setpoint = scored_setpoint_candidates[0].setpoint_after
        if new_setpoint is None:
            await _log_blocked(
                automation, zone, avg_temp,
                "Ação ignorada: não há ajuste de 1°C que respeite a faixa ideal e os limites do aparelho.",
                session,
            )
            return

        if not (automation.setpoint_min <= new_setpoint <= automation.setpoint_max):
            await _log_blocked(
                automation, zone, avg_temp,
                f"Setpoint {new_setpoint}°C fora dos limites permitidos ({automation.setpoint_min}–{automation.setpoint_max}°C)",
                session,
            )
            return

        # Guard: rejeitar no-op — o setpoint efetivo não pode ser igual ao atual
        effective_new = max(automation.setpoint_min, min(automation.setpoint_max, new_setpoint))
        if effective_new == best_params.setpoint_cool:
            await _log_blocked(
                automation, zone, avg_temp,
                f"Ação ignorada: setpoint de {best_device.device.name} já está em "
                f"{best_params.setpoint_cool}°C — nenhuma alteração útil dentro dos limites "
                f"{automation.setpoint_min}–{automation.setpoint_max}°C.",
                session,
            )
            return

        confidence = _confidence(avg_temp, zone, status, len(readable))
        energy_payload = _energy_decision_payload(
            zone=zone,
            status=status,
            strategy=energy_strategy,
            avg_temp=avg_temp,
            devices=devices,
            params_map=params_map,
            selected=scored_setpoint_candidates[0],
            candidates=scored_setpoint_candidates,
        )
        reason = _build_reason(avg_temp, zone, status, best_device.device, direction, trend, hotspot=hotspot)
        reason = _append_energy_decision(reason, energy_payload)

        # Captura ANTES de _execute_setpoint modificar params.setpoint_cool
        setpoint_before = best_params.setpoint_cool

        action_status = "suggestion"
        block_reason = None
        _api_ms: int | None = None

        if automation.mode in ("auto", "semi"):
            if not await _device_window_ok(best_device.device.id):
                await _log_blocked(
                    automation, zone, avg_temp,
                    f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                    f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                    f"{best_device.device.name}",
                    session,
                )
                return
            # acquire_lock é atômico (SET NX EX) — evita race entre múltiplos workers
            if not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                return  # outro worker chegou primeiro entre o exists() e agora
            ok, _api_ms = await _execute_setpoint(
                best_device.device, best_params, direction, automation, session,
                step=step, zone_status=status,
            )
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

        _setpoint_api_ms = _api_ms
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
            decision_ms=int((time.monotonic() - _t0) * 1000),
            api_ms=_setpoint_api_ms,
        )
        session.add(action)
        await session.commit()
        try:
            _sc = scored_setpoint_candidates[0]
            _dec_type = "auto" if action_status == "pending_verification" else "suggestion"
            await _learning_record(
                session=session,
                zone_action_id=action.id,
                store_id=automation.store_id,
                zone_key=zone.key,
                zone_label=zone.label,
                decision_type=_dec_type,
                thermal_status=status,
                avg_temp=round(avg_temp, 2),
                ideal_min=zone.ideal_min,
                ideal_max=zone.ideal_max,
                trend_c_per_hour=trend,
                freshness_ratio=None,
                devices_on=sum(1 for r in devices if _device_is_on(r, params_map.get(r.device.id))),
                devices_off=sum(1 for r in devices if _device_is_off(r, params_map.get(r.device.id))),
                had_hotspot=hotspot is not None,
                hotspot_peak_temp=hotspot.peak_temp if hotspot else None,
                action_type="setpoint_down" if direction == "down" else "setpoint_up",
                device_id=best_device.device.id,
                device_name=best_device.device.name,
                setpoint_from=setpoint_before,
                setpoint_to=new_setpoint,
                fan_speed_from=best_params.fan_speed,
                fan_speed_to=None,
                confidence=confidence,
                energy_strategy=energy_strategy,
                thermal_impact_score=_sc.thermal_impact_score,
                energy_cost_score=_sc.energy_cost_score,
                final_score=_sc.final_score,
            )
            await session.commit()
        except Exception as _le:
            logger.warning("learning record falhou (setpoint): %s", _le)

        if action_status == "pending_verification" and _setpoint_api_ms is not None:
            logger.info(
                "Zone %s: decisão em %dms, API em %dms",
                zone.key,
                int((time.monotonic() - _t0) * 1000),
                _setpoint_api_ms,
            )

        await redis_client.publish("zone.action.created", {
            "store_id": str(automation.store_id),
            "zone_key": zone.key,
            "zone_label": zone.label,
            "device_name": best_device.device.name,
            "direction": direction,
            "status": action_status,
            "confidence": round(confidence * 100),
            "setpoint_before": setpoint_before,
            "setpoint_after": new_setpoint,
            "energy_strategy": energy_strategy,
            "energy_decision": energy_payload,
        })


# ── Verificação de resultado ──────────────────────────────────────────────────

async def _verify_action(action: ZoneAction, session: AsyncSession) -> None:
    zone = ZONES.get(action.zone_key)
    if zone is None:
        # Tenta carregar como zona customizada
        from app.models.custom_zone import CustomZone, CustomZoneDevice
        cz_res = await session.execute(
            select(CustomZone).where(CustomZone.zone_key == action.zone_key)
        )
        cz = cz_res.scalar_one_or_none()
        if cz:
            dev_res = await session.execute(
                select(CustomZoneDevice.device_id).where(CustomZoneDevice.zone_id == cz.id)
            )
            device_ids = [r[0] for r in dev_res.all()]
            zone = ZoneConfig(
                key=cz.zone_key, label=cz.name, sector_names=[],
                ideal_min=cz.ideal_min, ideal_max=cz.ideal_max,
                zone_type=cz.zone_type, device_ids=device_ids,
            )
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


def _is_thermal_observation_source(row: _DeviceRow) -> bool:
    return (
        row.status.temperature is not None
        and row.status.status_classification not in THERMAL_OBSERVATION_BLOCKED_STATUSES
        and not row.device.dnd
    )


def _is_setpoint_readable_source(row: _DeviceRow) -> bool:
    return (
        _is_thermal_observation_source(row)
        and not row.device.source_url
        and row.status.status_classification not in BLOCKED_STATUSES
        and row.status.state is not False
    )


async def _get_zone_devices(
    store_id: uuid.UUID, zone: ZoneConfig, session: AsyncSession
) -> tuple[list[_DeviceRow], dict[uuid.UUID, DeviceParameters]]:
    if zone.device_ids is not None:
        # Zona personalizada: filtra por IDs de device
        if not zone.device_ids:
            return [], {}
        result = await session.execute(
            select(Device, DeviceStatusLatest)
            .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .where(Device.active == True, Device.id.in_(zone.device_ids))
        )
    else:
        # Zona padrão: filtra por nomes de setor
        result = await session.execute(
            select(Device, DeviceStatusLatest)
            .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .where(
                Device.active == True,
                StoreSector.store_id == store_id,
                StoreSector.name.in_(zone.sector_names),
            )
        )
    rows = result.all()
    devices = []
    for device, status in rows:
        if status is None:
            status = DeviceStatusLatest(
                device_id=device.id,
                state=None,
                temperature=None,
                status_classification="SEM_LEITURA",
                updated_at=None,
            )
        devices.append(_DeviceRow(device, status))

    if not devices:
        return [], {}
    device_ids = [r.device.id for r in devices]
    params_result = await session.execute(
        select(DeviceParameters).where(DeviceParameters.device_id.in_(device_ids))
    )
    params_map = {p.device_id: p for p in params_result.scalars().all()}
    return devices, params_map



async def _sync_zone_parameters_from_brise(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    session: AsyncSession,
) -> None:
    """Atualiza setpoint real dos ACs antes de decidir automação da zona."""
    changed = False
    for row in devices:
        if row.device.source_url is not None:
            continue
        remote = await brise_client.get_parameters(row.device.brise_device_id)
        if remote is None:
            continue

        params = params_map.get(row.device.id)
        if params is None:
            params = DeviceParameters(device_id=row.device.id)
            params_map[row.device.id] = params
            session.add(params)

        before = params.setpoint_cool
        params.mode_device = remote.modeDevice if remote.modeDevice is not None else params.mode_device
        params.mode_ac = remote.modeAC if remote.modeAC is not None else params.mode_ac
        params.fan_speed = remote.fanSpeed if remote.fanSpeed is not None else params.fan_speed
        params.setpoint_cool = remote.setpointCool if remote.setpointCool is not None else params.setpoint_cool
        params.setpoint_heat = remote.setpointHeat if remote.setpointHeat is not None else params.setpoint_heat
        params.eco_cool = remote.ecoCool if remote.ecoCool is not None else params.eco_cool
        params.eco_heat = remote.ecoHeat if remote.ecoHeat is not None else params.eco_heat
        params.synced_at = datetime.utcnow()
        changed = True

        if before != params.setpoint_cool:
            logger.info(
                "Setpoint real sincronizado Brise: %s (%s) %s°C → %s°C",
                row.device.name,
                row.device.brise_device_id,
                before,
                params.setpoint_cool,
            )

        await set_device_params(row.device.id, {
            "mode_device": params.mode_device,
            "mode_ac": params.mode_ac,
            "fan_speed": params.fan_speed,
            "setpoint_cool": params.setpoint_cool,
            "setpoint_heat": params.setpoint_heat,
            "eco_cool": params.eco_cool,
            "eco_heat": params.eco_heat,
            "synced_at": params.synced_at.isoformat(),
            "source": "brise_api",
        })

    if changed:
        await session.commit()

def _local_hotspot_status(hotspot: Hotspot | None, zone: ZoneConfig) -> str | None:
    """Retorna severidade local quando a média está confortável, mas há subárea quente."""
    if hotspot is None or hotspot.peak_temp <= zone.ideal_max:
        return None
    status = _classify(hotspot.peak_temp, zone.ideal_min, zone.ideal_max)
    return status if status in ("WARM", "HOT", "CRITICAL") else None


def _device_command_communication_ok(row: _DeviceRow) -> bool:
    """Valida se o aparelho tem telemetria recente o bastante para receber comando.

    Aparelhos DESLIGADO não emitem leitura de temperatura entre polls; usam janela
    4× maior para não serem descartados indevidamente do pool de power_on.
    SEM_LEITURA / LEITURA_STALE / AGUARDANDO_LEITURA / COMPRESSOR_CYCLING → inelegíveis em qualquer caso.
    """
    status = row.status.status_classification
    if status in {"SEM_LEITURA", "LEITURA_STALE", "AGUARDANDO_LEITURA", "COMPRESSOR_CYCLING"}:
        return False

    updated_at = getattr(row.status, "updated_at", None)
    if not isinstance(updated_at, datetime):
        return False

    is_confirmed_off = status == "DESLIGADO" or row.status.state is False
    threshold_minutes = (
        settings.offline_threshold_minutes * 4 if is_confirmed_off
        else settings.offline_threshold_minutes
    )
    return updated_at >= datetime.utcnow() - timedelta(minutes=threshold_minutes)


def _safe_float(value, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _energy_strategy(automation: ZoneAutomation | None) -> str:
    priority = getattr(automation, "priority", None) or "conforto"
    if priority == "economia":
        return "economy"
    if priority == "estabilidade":
        return "balanced"
    if priority == "critico":
        return "critical"
    if getattr(automation, "is_critical_zone", False):
        return "critical"
    return "comfort_first"


def _estimated_device_kw(row: _DeviceRow) -> float:
    """Estimativa conservadora de kW para comparar candidatos.

    A Brise pode fornecer `consumption_estimated`; quando não houver, cai para
    uma aproximação por BTU para não escolher só por nome ou ordem da lista.
    """
    raw = _safe_float(getattr(row.status, "consumption_estimated", None))
    if raw is not None and raw > 0:
        return max(0.1, raw * settings.energy_consumption_scale)
    btu = _safe_float(getattr(row.device, "btu", None), 12000.0) or 12000.0
    return max(0.5, (btu / 12000.0) * 1.1)


def _device_efficiency(row: _DeviceRow) -> float:
    raw = _safe_float(getattr(row.status, "efficiency_score", None))
    if raw is None:
        return 0.72
    if raw > 1:
        raw = raw / 100.0
    return max(0.2, min(1.0, raw))


def _device_is_off(row: _DeviceRow, params: DeviceParameters | None) -> bool:
    return (
        row.status.status_classification == "DESLIGADO"
        or row.status.state is False
        or (params is not None and getattr(params, "mode_device", None) == 0)
    )


def _device_is_on(row: _DeviceRow, params: DeviceParameters | None) -> bool:
    if _device_is_off(row, params):
        return False
    return row.status.state is True or (params is not None and getattr(params, "mode_device", None) == 1)


def _minutes_since_state_change(row: _DeviceRow, on_state: bool) -> int | None:
    attr = "accumulated_on_minutes" if on_state else "accumulated_off_minutes"
    return _safe_int(getattr(row.status, attr, None))


def _normal_cooling_floor(zone: ZoneConfig, automation: ZoneAutomation, status: str) -> int:
    """Menor setpoint permitido no ciclo de resfriamento.

    O piso é sempre setpoint_min (limite definido pelo operador).
    Usar ideal_max como piso bloqueava zonas onde o setpoint já estava abaixo de
    ideal_max (ex.: AC em 24°C, ideal_max=26°C → floor=26, current<=floor → sem ajuste),
    mesmo com a sala ainda acima da faixa confortável.
    """
    return automation.setpoint_min


def _power_on_setpoint(params: DeviceParameters, zone: ZoneConfig, automation: ZoneAutomation, status: str) -> int:
    current = _safe_int(getattr(params, "setpoint_cool", None), int(math.ceil(zone.ideal_max))) or int(math.ceil(zone.ideal_max))
    floor = _normal_cooling_floor(zone, automation, status)
    return max(floor, min(automation.setpoint_max, current))


def _planned_setpoint_after(
    params: DeviceParameters,
    direction: str,
    zone: ZoneConfig | None,
    automation: ZoneAutomation | None,
    status: str,
    *,
    setpoint_min: int,
    setpoint_max: int,
) -> int | None:
    current = _safe_int(getattr(params, "setpoint_cool", None))
    if current is None:
        return None
    if direction == "up":
        target = min(setpoint_max, current + 1)
        return target if target != current else None
    if zone is not None and automation is not None:
        floor = _normal_cooling_floor(zone, automation, status)
    else:
        floor = setpoint_min
    if current <= floor:
        return None
    target = max(floor, current - 1)
    return target if target != current else None


def _candidate_proximity(row: _DeviceRow, hotspot: Hotspot | None) -> float:
    return proximity_score(
        row.device.position_x,
        row.device.position_y,
        hotspot=hotspot,
        influence_radius_m=float(row.device.influence_radius_m or 8),
    )


def _score_power_on_candidate(
    row: _DeviceRow,
    params: DeviceParameters,
    *,
    hotspot: Hotspot | None,
    strategy: str,
    devices_on: int,
) -> EnergyCandidate | None:
    off_minutes = _minutes_since_state_change(row, on_state=False)
    if off_minutes is not None and off_minutes < MIN_OFF_BEFORE_POWER_ON_MINUTES:
        return None

    prox = _candidate_proximity(row, hotspot)
    kw = _estimated_device_kw(row)
    efficiency = _device_efficiency(row)
    strategy_penalty = {"economy": 18.0, "balanced": 10.0, "comfort_first": 6.0, "critical": 2.0}.get(strategy, 10.0)
    thermal = 42.0 + prox * 45.0 + min(float(row.device.btu or 0) / 24000.0, 1.0) * 8.0
    energy_cost = kw * 14.0 + (1.0 - efficiency) * 18.0 + 16.0 + devices_on * 2.5 + strategy_penalty
    if hotspot and hotspot.has_coordinates:
        thermal += prox * 10.0
    reason = (
        "Aparelho desligado próximo ao hotspot; ação localizada evita baixar setpoint de vários aparelhos."
        if hotspot else
        "Aparelho desligado acrescenta capacidade; custo penalizado para evitar ligar equipamento sem necessidade."
    )
    return EnergyCandidate(
        action="power_on",
        row=row,
        params=params,
        thermal_impact_score=round(thermal, 1),
        energy_cost_score=round(energy_cost, 1),
        final_score=round(thermal - energy_cost, 1),
        reason=reason,
    )


def _score_setpoint_candidate(
    row: _DeviceRow,
    params: DeviceParameters,
    *,
    direction: str,
    zone: ZoneConfig | None,
    automation: ZoneAutomation | None,
    status: str,
    hotspot: Hotspot | None,
    setpoint_min: int,
    setpoint_max: int,
    strategy: str,
) -> EnergyCandidate | None:
    setpoint_after = _planned_setpoint_after(
        params,
        direction,
        zone,
        automation,
        status,
        setpoint_min=setpoint_min,
        setpoint_max=setpoint_max,
    )
    if setpoint_after is None:
        return None

    prox = _candidate_proximity(row, hotspot)
    kw = _estimated_device_kw(row)
    efficiency = _device_efficiency(row)
    delta_abs = abs(_safe_float(getattr(row.status, "delta_temp", None), 0.0) or 0.0)
    thermal = 30.0 + prox * 38.0 + min(delta_abs * 6.0, 18.0)
    if _device_is_on(row, params):
        thermal += 8.0
    # Device no pico do hotspot: bônus direto para garantir prioridade sobre vizinhos
    if hotspot is not None and hotspot.peak_device_name and row.device.name == hotspot.peak_device_name:
        thermal += 20.0

    low_setpoint_penalty = 0.0
    if direction == "down" and zone is not None:
        low_setpoint_penalty = max(0.0, zone.ideal_min - setpoint_after) * 18.0
    strategy_penalty = {"economy": 10.0, "balanced": 5.0, "comfort_first": 2.0, "critical": 0.0}.get(strategy, 5.0)
    energy_cost = kw * 10.0 + (1.0 - efficiency) * 16.0 + low_setpoint_penalty + strategy_penalty
    action = "set_temperature_down" if direction == "down" else "set_temperature_up"
    reason = (
        "Ajuste de 1°C em aparelho já ligado e influente; evita ação global e setpoint agressivo."
        if direction == "down" else
        "Zona fria: elevar setpoint economiza energia antes de desligar equipamento."
    )
    return EnergyCandidate(
        action=action,
        row=row,
        params=params,
        thermal_impact_score=round(thermal, 1),
        energy_cost_score=round(energy_cost, 1),
        final_score=round(thermal - energy_cost, 1),
        reason=reason,
        setpoint_after=setpoint_after,
    )


def _build_power_on_candidates(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    *,
    hotspot: Hotspot | None,
    strategy: str,
) -> list[EnergyCandidate]:
    devices_on = sum(1 for row in devices if _device_is_on(row, params_map.get(row.device.id)))
    candidates: list[EnergyCandidate] = []
    for row in devices:
        if row.device.dnd or row.device.source_url:
            continue
        if not _device_command_communication_ok(row):
            logger.debug(
                "power_on_candidate: %s excluído — communication_ok=False "
                "(status=%s, updated_at=%s, state=%s)",
                row.device.name,
                row.status.status_classification,
                getattr(row.status, "updated_at", None),
                row.status.state,
            )
            continue
        params = params_map.get(row.device.id)
        if params is None:
            params = DeviceParameters(
                device_id=row.device.id,
                mode_device=0,
                mode_ac=0,
                fan_speed=1,
                setpoint_cool=22,
                setpoint_heat=28,
                eco_cool=False,
                eco_heat=False,
            )
        if not _device_is_off(row, params):
            continue
        scored = _score_power_on_candidate(row, params, hotspot=hotspot, strategy=strategy, devices_on=devices_on)
        if scored is not None:
            candidates.append(scored)

    candidates.sort(
        key=lambda item: (
            item.final_score,
            _candidate_proximity(item.row, hotspot),  # type: ignore[arg-type]
            -(item.energy_cost_score),
            getattr(item.row.device, "name", "") or "",  # type: ignore[attr-defined]
        ),
        reverse=True,
    )
    return candidates


def _build_setpoint_candidates(
    readable: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    *,
    direction: str,
    setpoint_min: int,
    setpoint_max: int,
    hotspot: Hotspot | None,
    zone: ZoneConfig | None,
    automation: ZoneAutomation | None,
    status: str,
    strategy: str,
) -> list[EnergyCandidate]:
    candidates: list[EnergyCandidate] = []
    for row in readable:
        if row.device.dnd or row.device.source_url:
            continue
        if not _device_command_communication_ok(row):
            continue
        params = params_map.get(row.device.id)
        if params is None or getattr(params, "setpoint_cool", None) is None:
            continue
        if direction == "down" and not _device_is_on(row, params):
            continue
        scored = _score_setpoint_candidate(
            row,
            params,
            direction=direction,
            zone=zone,
            automation=automation,
            status=status,
            hotspot=hotspot,
            setpoint_min=setpoint_min,
            setpoint_max=setpoint_max,
            strategy=strategy,
        )
        if scored is not None:
            candidates.append(scored)

    candidates.sort(
        key=lambda item: (
            item.final_score,
            _candidate_proximity(item.row, hotspot),  # type: ignore[arg-type]
            abs(_safe_float(getattr(item.row.status, "delta_temp", None), 0.0) or 0.0),  # type: ignore[attr-defined]
            getattr(item.row.device, "name", "") or "",  # type: ignore[attr-defined]
        ),
        reverse=True,
    )
    return candidates


def _energy_decision_payload(
    *,
    zone: ZoneConfig,
    status: str,
    strategy: str,
    avg_temp: float,
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    selected: EnergyCandidate | None,
    candidates: list[EnergyCandidate],
) -> dict:
    devices_on = sum(1 for row in devices if _device_is_on(row, params_map.get(row.device.id)))
    devices_off = sum(1 for row in devices if _device_is_off(row, params_map.get(row.device.id)))
    return {
        "zone_label": zone.label,
        "thermal_status": status.lower(),
        "energy_strategy": strategy,
        "current_temperature": round(avg_temp, 2),
        "target_range": [zone.ideal_min, zone.ideal_max],
        "devices_on": devices_on,
        "devices_off": devices_off,
        "candidate_actions": [
            {
                "action": candidate.action,
                "device": getattr(candidate.row.device, "name", None),  # type: ignore[attr-defined]
                "from": getattr(candidate.params, "setpoint_cool", None),
                "to": candidate.setpoint_after,
                "thermal_impact_score": candidate.thermal_impact_score,
                "energy_cost_score": candidate.energy_cost_score,
                "final_score": candidate.final_score,
                "estimated_kw": round(_estimated_device_kw(candidate.row), 2),  # type: ignore[arg-type]
                "reason": candidate.reason,
            }
            for candidate in candidates[:5]
        ],
        "selected_action": selected.action if selected else "none",
        "selected_device": getattr(selected.row.device, "name", None) if selected else None,  # type: ignore[attr-defined]
        "selected_reason": selected.reason if selected else "Nenhuma ação necessária com menor custo energético.",
    }


def _append_energy_decision(reason: str, payload: dict) -> str:
    selected = payload.get("selected_device")
    strategy = payload.get("energy_strategy")
    action = payload.get("selected_action")
    if selected:
        summary = (
            f"Energia: estratégia {strategy}; escolhido {action} em {selected} "
            "por resolver localmente com menor custo estimado."
        )
    else:
        summary = f"Energia: estratégia {strategy}; nenhuma ação para evitar consumo desnecessário."
    return f"{reason} {summary}\n\nenergy_decision={json.dumps(payload, ensure_ascii=False)}"


def _zone_energy_waste(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    zone: ZoneConfig,
    avg_temp: float,
    trend: float | None,
) -> tuple[bool, str]:
    on_rows = [row for row in devices if not row.device.source_url and _device_is_on(row, params_map.get(row.device.id))]
    if not on_rows:
        return False, ""
    low_setpoints = [
        row for row in on_rows
        if (params_map.get(row.device.id) is not None)
        and (params_map[row.device.id].setpoint_cool or 99) < math.ceil(zone.ideal_min)
    ]
    total_kw = sum(_estimated_device_kw(row) for row in on_rows)
    stable_or_falling = trend is None or trend <= 0.6
    too_cold_edge = avg_temp <= zone.ideal_min + 0.3 and stable_or_falling
    many_on = len(on_rows) >= 3 and stable_or_falling
    high_kw = total_kw >= 4.0 and stable_or_falling
    if low_setpoints or too_cold_edge or (many_on and high_kw):
        reason = (
            f"Zona confortável em {avg_temp:.1f}°C, {len(on_rows)} aparelho(s) ligado(s), "
            f"potência estimada {total_kw:.1f} kW. "
            "Oportunidade de economia: elevar setpoint em 1°C nos aparelhos mais baixos "
            "ou desligar redundante após respeitar tempo mínimo ligado."
        )
        return True, reason
    return False, ""


def _hotspot_area_key(hotspot: Hotspot | None) -> str:
    if hotspot is None:
        return "no_hotspot"
    if hotspot.has_coordinates:
        bucket_x = int((hotspot.x or 0) // 50)
        bucket_y = int((hotspot.y or 0) // 50)
        return f"xy:{bucket_x}:{bucket_y}"
    names = ",".join(sorted(hotspot.contributing_names or []))
    return f"names:{names or 'unknown'}"


def _suggestion_signature(
    *,
    zone: ZoneConfig,
    hotspot: Hotspot | None,
    issue_type: str,
    action_type: str,
    target_devices: list[uuid.UUID | str],
    severity: str,
    setpoint_after: int | None = None,
) -> str:
    payload = {
        "zone_id": zone.key,
        "hotspot_area": _hotspot_area_key(hotspot),
        "issue_type": issue_type,
        "recommended_action_type": action_type,
        "target_devices": sorted(str(d) for d in target_devices),
        "severity": severity,
        "setpoint_after": setpoint_after,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _save_zone_action(action: ZoneAction, session: AsyncSession) -> tuple[ZoneAction, bool]:
    """Persiste a ação ou atualiza sugestão aberta/recentemente repetida."""
    signature = getattr(action, "suggestion_signature", None)
    if action.status == "suggestion" and signature:
        since = datetime.utcnow() - timedelta(seconds=SUGGESTION_DEDUPE_SECONDS)
        existing_result = await session.execute(
            select(ZoneAction)
            .where(
                ZoneAction.store_id == action.store_id,
                ZoneAction.zone_key == action.zone_key,
                ZoneAction.status == "suggestion",
                ZoneAction.suggestion_signature == signature,
                ZoneAction.created_at >= since,
            )
            .order_by(ZoneAction.created_at.desc())
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            existing.zone_label = action.zone_label
            existing.device_id = action.device_id
            existing.device_name = action.device_name
            existing.direction = action.direction
            existing.temp_before = action.temp_before
            existing.temp_after = action.temp_after
            existing.ideal_min = action.ideal_min
            existing.ideal_max = action.ideal_max
            existing.setpoint_before = action.setpoint_before
            existing.setpoint_after = action.setpoint_after
            existing.reason = action.reason
            existing.confidence = action.confidence
            existing.mode = action.mode
            existing.block_reason = action.block_reason
            existing.decision_ms = action.decision_ms
            existing.api_ms = action.api_ms
            existing.attempt_count = (existing.attempt_count or 1) + 1
            existing.created_at = datetime.utcnow()
            await session.commit()
            return existing, True

    session.add(action)
    await session.commit()
    return action, False


def _select_best_device(
    readable: list[_DeviceRow],
    status: str,
    params_map: dict[uuid.UUID, DeviceParameters],
    direction: str,
    setpoint_min: int,
    setpoint_max: int,
    hotspot: "Hotspot | None" = None,
    zone: ZoneConfig | None = None,
    automation: ZoneAutomation | None = None,
    strategy: str = "balanced",
) -> tuple[_DeviceRow, DeviceParameters] | None:
    scored = _build_setpoint_candidates(
        readable,
        params_map,
        direction=direction,
        setpoint_min=setpoint_min,
        setpoint_max=setpoint_max,
        hotspot=hotspot,
        zone=zone,
        automation=automation,
        status=status,
        strategy=strategy,
    )
    if scored:
        best = scored[0]
        return best.row, best.params  # type: ignore[return-value]

    going_down = direction == "down"
    candidates = [
        r for r in readable
        if r.device.id in params_map
        and not r.device.source_url
        and (params_map[r.device.id].setpoint_cool > setpoint_min if going_down
             else params_map[r.device.id].setpoint_cool < setpoint_max)
    ]
    if not candidates:
        return None

    def sort_key(row: _DeviceRow) -> tuple[float, float]:
        prox = proximity_score(
            row.device.position_x,
            row.device.position_y,
            hotspot=hotspot,
            influence_radius_m=float(row.device.influence_radius_m or 8),
        )
        delta = row.status.delta_temp
        delta_abs = abs(delta) if delta is not None else 0.0
        return (prox, delta_abs)

    candidates.sort(key=sort_key, reverse=True)
    best = candidates[0]
    return best, params_map[best.device.id]


def _select_hotspot_setpoint_candidates(
    readable: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    setpoint_min: int,
    hotspot: "Hotspot | None" = None,
    zone: ZoneConfig | None = None,
    automation: ZoneAutomation | None = None,
    status: str = "WARM",
    strategy: str = "balanced",
) -> list[tuple[_DeviceRow, DeviceParameters]]:
    """Retorna ACs ligados, comunicando e com margem real para reduzir setpoint."""
    setpoint_max = automation.setpoint_max if automation is not None else 30
    scored = _build_setpoint_candidates(
        readable,
        params_map,
        direction="down",
        setpoint_min=setpoint_min,
        setpoint_max=setpoint_max,
        hotspot=hotspot,
        zone=zone,
        automation=automation,
        status=status,
        strategy=strategy,
    )
    if scored:
        return [(candidate.row, candidate.params) for candidate in scored]  # type: ignore[misc]

    candidates: list[_DeviceRow] = []
    for row in readable:
        if row.device.dnd or row.device.source_url:
            continue
        if not _device_command_communication_ok(row):
            continue
        params = params_map.get(row.device.id)
        if params is None or params.setpoint_cool is None:
            continue
        if row.status.state is False or row.status.status_classification == "DESLIGADO" or params.mode_device == 0:
            continue
        is_on = (
            row.status.state is True
            or row.status.status_classification not in BLOCKED_STATUSES
            or params.mode_device == 1
        )
        if not is_on:
            continue
        if params.setpoint_cool <= setpoint_min:
            continue
        candidates.append(row)

    candidates.sort(
        key=lambda row: (
            proximity_score(
                row.device.position_x,
                row.device.position_y,
                hotspot=hotspot,
                influence_radius_m=float(row.device.influence_radius_m or 8),
            ),
            params_map[row.device.id].setpoint_cool or 0,
            abs(row.status.delta_temp or 0.0),
            row.device.name or "",
        ),
        reverse=True,
    )
    return [(row, params_map[row.device.id]) for row in candidates]


def _select_power_on_candidate(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    hotspot: "Hotspot | None" = None,
    strategy: str = "balanced",
) -> tuple[_DeviceRow, DeviceParameters] | None:
    candidates = _build_power_on_candidates(
        devices,
        params_map,
        hotspot=hotspot,
        strategy=strategy,
    )
    if not candidates:
        logger.debug(
            "power_on_candidate: nenhum candidato OFF disponível "
            "(hotspot=%s)",
            f"({hotspot.x:.0f},{hotspot.y:.0f}) peak={hotspot.peak_temp:.1f}°C"
            if hotspot and hotspot.has_coordinates else hotspot,
        )
        return None

    best_candidate = candidates[0]
    best = best_candidate.row  # type: ignore[assignment]
    best_prox = proximity_score(
        best.device.position_x,
        best.device.position_y,
        hotspot=hotspot,
        influence_radius_m=float(best.device.influence_radius_m or 8),
    )
    logger.debug(
        "power_on_candidate: %s selecionado (proximity=%.3f, btu=%s, pos=(%s,%s), hotspot=%s)",
        best.device.name,
        best_prox,
        best.device.btu,
        best.device.position_x,
        best.device.position_y,
        f"({hotspot.x:.0f},{hotspot.y:.0f}) peak={hotspot.peak_temp:.1f}°C"
        if hotspot and hotspot.has_coordinates else hotspot,
    )

    # Se não há params, cria um objeto temporário com defaults seguros para ligar
    params = best_candidate.params  # type: ignore[assignment]
    if params is None:
        params = DeviceParameters(
            device_id=best.device.id,
            mode_device=0,
            mode_ac=0,
            fan_speed=1,
            setpoint_cool=22,
            setpoint_heat=28,
            eco_cool=False,
            eco_heat=False,
        )
    return best, params


async def _execute_power_on(
    device: Device,
    params: DeviceParameters,
    session: AsyncSession,
    target_setpoint: int | None = None,
    zone_status: str = "WARM",
) -> tuple[bool, int]:
    from app.services.action_dispatcher import brise_dispatcher

    if not await brise_dispatcher.can_execute():
        logger.warning(
            "_execute_power_on: circuit breaker OPEN — %s bloqueado", device.name
        )
        return False, 0

    setpoint_cool = target_setpoint or params.setpoint_cool or 22
    fan_speed = _target_fan_speed(zone_status, params.fan_speed)
    brise_params = {
        "modeDevice": 1,
        "modeAC": 0,
        "fanSpeed": fan_speed,
        "setpointCool": setpoint_cool,
        "setpointHeat": params.setpoint_heat or 28,
        "ecoCool": params.eco_cool or False,
        "ecoHeat": params.eco_heat or False,
    }

    _t_api = time.monotonic()
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    _api_ms = int((time.monotonic() - _t_api) * 1000)
    if success:
        await brise_dispatcher.on_success()
        params.mode_device = 1
        params.mode_ac = 0
        params.setpoint_cool = setpoint_cool
        params.fan_speed = fan_speed
        params.synced_at = datetime.utcnow()
        # Persiste o params se for novo (sem pk — device sem histórico de configuração)
        if params.id is None:
            session.add(params)
        if device.status_latest:
            device.status_latest.state = True
            device.status_latest.updated_at = datetime.utcnow()
        await session.commit()
    else:
        await brise_dispatcher.on_failure()
    return success, _api_ms


async def _try_power_off_cold_zone(
    automation: ZoneAutomation,
    zone: ZoneConfig,
    devices: list,
    params_map: dict,
    avg_temp: float,
    trend: float | None,
    status: str,
    energy_strategy: str,
    hotspot,
    _t0: float,
    session: AsyncSession,
) -> None:
    """Desliga o AC menos impactante quando a zona está fria e todos estão no setpoint_max.

    Só executa se:
    - O AC estiver ligado há pelo menos MIN_ON_BEFORE_ECONOMY_OFF_MINUTES
    - A tendência não estiver aquecendo (zona já está resolvendo sozinha)
    - Circuit breaker não estiver aberto
    """
    # Zona com circulação de pessoas (farma/loja): nunca desligar AC automaticamente
    if not automation.allow_auto_power_off:
        reason = (
            f"Zona {status} ({avg_temp:.1f}°C) com todos os ACs no setpoint máximo "
            f"({automation.setpoint_max}°C). Desligamento automático desabilitado para "
            f"esta zona (circulação de pessoas). Faixa: {automation.setpoint_min}–{automation.setpoint_max}°C. [{zone.key}]"
        )
        await _log_blocked(automation, zone, avg_temp, reason, session)
        return

    # Se zona está aquecendo por conta própria, aguarda — não precisa desligar
    if trend is not None and trend > 0.5:
        logger.debug("Zone %s: fria mas aquecendo a %.1f°C/h — aguardando", zone.key, trend)
        return

    # Candidatos a desligar: ACs ligados com tempo mínimo de operação
    candidates_off = []
    for row in devices:
        params = params_map.get(row.device.id)
        if not _device_is_on(row, params):
            continue
        if row.device.dnd or row.device.source_url:
            continue
        if not _device_command_communication_ok(row):
            continue
        on_minutes = _minutes_since_state_change(row, on_state=True)
        if on_minutes is not None and on_minutes < MIN_ON_BEFORE_ECONOMY_OFF_MINUTES:
            continue  # ligado há pouco tempo — não desligar ainda
        candidates_off.append((row, params, on_minutes or 0))

    if not candidates_off:
        # Nenhum AC elegível para desligar — loga bloqueio normal
        reason = (
            f"Zona {status} com setpoint no máximo ({automation.setpoint_max}°C). "
            f"Nenhum AC elegível para desligar (todos ligados há menos de "
            f"{MIN_ON_BEFORE_ECONOMY_OFF_MINUTES} min ou sem comunicação). "
            f"Faixa: {automation.setpoint_min}–{automation.setpoint_max}°C. [{zone.key}]"
        )
        await _log_blocked(automation, zone, avg_temp, reason, session)
        return

    # Prioriza desligar o AC com maior BTU (mais impactante para aquecer) entre os que
    # estão ligados há mais tempo — equilibra conforto e energia
    candidates_off.sort(key=lambda x: (-x[2], -(x[0].device.btu or 0)))
    target_row, target_params, on_min = candidates_off[0]

    reason = (
        f"Zona {status} ({avg_temp:.1f}°C) com todos os ACs no setpoint máximo "
        f"({automation.setpoint_max}°C) e temperatura não respondendo"
        + (f" (tendência {trend:+.1f}°C/h)" if trend is not None else "")
        + f". Desligando {target_row.device.name} (ligado há {on_min} min) "
        f"para permitir aquecimento natural. [{zone.key}]"
    )

    action_status = "suggestion"
    _api_ms: int | None = None

    if automation.mode in ("auto", "semi"):
        cooldown_key = f"zone:cooldown:{automation.store_id}:{zone.key}"
        if not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
            return
        ok, _api_ms = await _execute_power_off(target_row.device, target_params, session)
        if ok:
            action_status = "pending_verification"
            logger.info(
                "Zone %s [%s]: desligando %s — zona fria no setpoint_max (%.1f°C, tendência %s)",
                zone.key, automation.mode, target_row.device.name, avg_temp,
                f"{trend:+.1f}°C/h" if trend is not None else "desconhecida",
            )
        else:
            action_status = "blocked"
            await redis_client.release_lock(cooldown_key)

    action = ZoneAction(
        store_id=automation.store_id,
        zone_key=zone.key,
        zone_label=zone.label,
        device_id=target_row.device.id,
        device_name=target_row.device.name,
        direction="up",
        temp_before=round(avg_temp, 2),
        ideal_min=zone.ideal_min,
        ideal_max=zone.ideal_max,
        setpoint_before=target_params.setpoint_cool,
        setpoint_after=target_params.setpoint_cool,
        reason=reason,
        confidence=_confidence(avg_temp, zone, status, 1),
        mode=automation.mode,
        status=action_status,
        decision_ms=int((time.monotonic() - _t0) * 1000),
        api_ms=_api_ms,
    )
    session.add(action)
    await session.commit()

    await redis_client.publish("zone.action.created", {
        "store_id": str(automation.store_id),
        "zone_key": zone.key,
        "zone_label": zone.label,
        "device_name": target_row.device.name,
        "direction": "up",
        "status": action_status,
        "action": "power_off",
        "reason": reason,
    })


async def _execute_power_off(
    device: Device,
    params: DeviceParameters,
    session: AsyncSession,
) -> tuple[bool, int]:
    from app.services.action_dispatcher import brise_dispatcher

    if not await brise_dispatcher.can_execute():
        logger.warning("_execute_power_off: circuit breaker OPEN — %s bloqueado", device.name)
        return False, 0

    brise_params = {
        "modeDevice": 0,
        "modeAC": params.mode_ac or 0,
        "fanSpeed": params.fan_speed or 1,
        "setpointCool": params.setpoint_cool or 26,
        "setpointHeat": params.setpoint_heat or 28,
        "ecoCool": params.eco_cool or False,
        "ecoHeat": params.eco_heat or False,
    }
    _t_api = time.monotonic()
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    _api_ms = int((time.monotonic() - _t_api) * 1000)
    if success:
        await brise_dispatcher.on_success()
        params.mode_device = 0
        params.synced_at = datetime.utcnow()
        if device.status_latest:
            device.status_latest.state = False
            device.status_latest.updated_at = datetime.utcnow()
        await session.commit()
    else:
        await brise_dispatcher.on_failure()
    return success, _api_ms


async def _execute_setpoint(
    device: Device,
    params: DeviceParameters,
    direction: str,
    automation: ZoneAutomation,
    session: AsyncSession,
    step: int = 1,
    zone_status: str = "WARM",
) -> tuple[bool, int]:
    from app.services.action_dispatcher import brise_dispatcher

    if not await brise_dispatcher.can_execute():
        logger.warning(
            "_execute_setpoint: circuit breaker OPEN — %s bloqueado", device.name
        )
        return False, 0

    delta = step if direction == "up" else -step
    new_setpoint = max(
        automation.setpoint_min,
        min(automation.setpoint_max, params.setpoint_cool + delta),
    )

    # Guard de segurança: nunca enviar comando que não muda nada
    if new_setpoint == params.setpoint_cool:
        logger.debug(
            "_execute_setpoint: no-op para %s (setpoint=%d já no alvo)",
            device.name, new_setpoint,
        )
        return False, 0

    fan_speed = _target_fan_speed(zone_status, params.fan_speed)
    brise_params = {
        "modeDevice": 1,
        "modeAC": 0,
        "fanSpeed": fan_speed,
        "setpointCool": new_setpoint,
        "setpointHeat": params.setpoint_heat,
        "ecoCool": params.eco_cool,
        "ecoHeat": params.eco_heat,
    }

    _t_api = time.monotonic()
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    _api_ms = int((time.monotonic() - _t_api) * 1000)
    if success:
        await brise_dispatcher.on_success()
        params.setpoint_cool = new_setpoint
        params.fan_speed = fan_speed
        params.synced_at = datetime.utcnow()
        await session.commit()
    else:
        await brise_dispatcher.on_failure()
    return success, _api_ms


# Mantido para métricas informacionais (daily_count no payload da API).
# Não é mais usado como guard de limite — o limite diário foi removido.
async def _daily_count(store_id: uuid.UUID, zone_key: str, session: AsyncSession) -> int:
    # Bug 16: usa meia-noite em horário de Manaus, não UTC
    from datetime import timezone
    now_local = datetime.now(LOCAL_TZ)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        select(func.count(ZoneAction.id)).where(
            ZoneAction.store_id == store_id,
            ZoneAction.zone_key == zone_key,
            # Bug 17: verified_failure não deve consumir limite diário se não houve comando efetivo
            ZoneAction.status.in_(["pending_verification", "executed", "verified_success"]),
            ZoneAction.created_at >= midnight_utc,
        )
    )
    return result.scalar() or 0


async def _device_window_ok(device_id: uuid.UUID) -> bool:
    """Retorna True se o device pode receber mais um comando na janela de 15 min.
    Usa Redis INCR via pipeline atômico. Fail-open: se Redis indisponível, permite o comando."""
    key = f"device:cmd_window:{device_id}"
    try:
        async with redis_client.client.pipeline(transaction=True) as pipe:
            await pipe.incr(key)
            await pipe.expire(key, DEVICE_WINDOW_SECONDS)
            results = await pipe.execute()
        count = results[0]
        if count > DEVICE_WINDOW_MAX_CMDS:
            await redis_client.client.decrby(key, 1)
            return False
        return True
    except Exception as exc:
        logger.warning("_device_window_ok: Redis indisponível, permitindo comando (%s)", exc)
        return True


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
    if device_id is None:
        if zone.device_ids:
            # Zonas customizadas: usa device_ids diretamente
            device_id = zone.device_ids[0]
        elif automation is not None:
            # Zonas legadas: busca por nome de setor
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


def _build_no_adjustable_reason(
    readable: list,
    devices: list,
    params_map: dict,
    direction: str,
    setpoint_min: int,
    setpoint_max: int,
    zone: "ZoneConfig",
) -> str:
    """Gera mensagem diagnóstica rica quando _select_best_device retorna None."""
    going_down = direction == "down"
    limit_val = setpoint_min if going_down else setpoint_max
    op = "mínimo" if going_down else "máximo"

    at_limit = [
        d for d in readable
        if d.device.id in params_map
        and (
            params_map[d.device.id].setpoint_cool <= setpoint_min if going_down
            else params_map[d.device.id].setpoint_cool >= setpoint_max
        )
    ]
    no_params = [d for d in readable if d.device.id not in params_map]
    off_in_zone = [
        d for d in devices
        if not d.device.source_url and not d.device.dnd
        and d.status.status_classification == "DESLIGADO"
    ]

    parts = []
    if at_limit:
        parts.append(f"{len(at_limit)} AC(s) com setpoint já no {op} permitido ({limit_val}°C)")
    if no_params:
        parts.append(f"{len(no_params)} AC(s) sem parâmetros registrados no banco")
    if off_in_zone:
        parts.append(
            f"{len(off_in_zone)} AC(s) desligados (não eligíveis para ajuste de setpoint — "
            "candidatos a power_on já tentados)"
        )
    if not parts:
        parts.append(f"nenhum AC com margem de ajuste na direção '{direction}'")

    return (
        f"Zona {zone.label}: {len(readable)} AC(s) com leitura, nenhum ajustável. "
        + "; ".join(parts) + f". Faixa: {setpoint_min}–{setpoint_max}°C."
    )


def _build_local_hotspot_power_on_reason(
    avg: float,
    zone: ZoneConfig,
    local_status: str,
    device: Device,
    trend: float | None,
    hotspot: Hotspot,
) -> str:
    labels = {"WARM": "subárea aquecendo", "HOT": "subárea quente", "CRITICAL": "subárea crítica"}
    trend_note = f" Tendência geral {trend:+.1f}°C/h." if trend is not None else ""
    near = hotspot.contributing_names[0] if hotspot.contributing_names else "ponto quente"
    return (
        f"Zona confortável na média ({avg:.1f}°C), mas há {labels.get(local_status, local_status)} "
        f"com pico de {hotspot.peak_temp:.1f}°C próximo a {near}."
        f"{trend_note} Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ligar {device.name} desligado próximo ao hotspot antes de reduzir setpoint da zona inteira."
    )


def _build_local_hotspot_setpoint_reason(
    avg: float,
    zone: ZoneConfig,
    local_status: str,
    device: Device,
    setpoint_before: int,
    setpoint_after: int,
    trend: float | None,
    hotspot: Hotspot,
    adjustable_names: list[str],
) -> str:
    labels = {"WARM": "subárea aquecendo", "HOT": "subárea quente", "CRITICAL": "subárea crítica"}
    trend_note = f" Tendência geral {trend:+.1f}°C/h." if trend is not None else ""
    near = hotspot.contributing_names[0] if hotspot.contributing_names else "ponto quente"
    adjustable = ", ".join(name for name in adjustable_names if name) or device.name
    return (
        f"Zona confortável na média ({avg:.1f}°C), mas há {labels.get(local_status, local_status)} "
        f"com pico de {hotspot.peak_temp:.1f}°C próximo a {near}.{trend_note} "
        f"Todos os aparelhos disponíveis próximos já estão ligados; ação localizada: reduzir setpoint "
        f"de {device.name} de {setpoint_before}°C para {setpoint_after}°C. "
        f"Aparelhos próximos ajustáveis: {adjustable}. Faixa ideal da zona {zone.ideal_min}–{zone.ideal_max}°C."
    )


async def _log_local_hotspot_suggestion(
    automation: ZoneAutomation,
    zone: ZoneConfig,
    avg_temp: float,
    local_status: str,
    trend: float | None,
    hotspot: Hotspot,
    session: AsyncSession,
    no_adjustable_reason: str | None = None,
) -> None:
    near = hotspot.contributing_names[0] if hotspot.contributing_names else "ponto quente"
    trend_note = f" Tendência geral {trend:+.1f}°C/h." if trend is not None else ""
    blocker = no_adjustable_reason or (
        "nenhum aparelho desligado comunicando e comandável está disponível perto do hotspot "
        "e nenhum aparelho ligado próximo possui margem segura de setpoint"
    )
    reason = (
        f"Zona confortável na média ({avg_temp:.1f}°C), mas hotspot local chegou a "
        f"{hotspot.peak_temp:.1f}°C próximo a {near}.{trend_note} "
        f"{blocker}; verificar balanceamento de ar, insuflação, retorno, carga térmica ou manutenção."
    )
    signature = _suggestion_signature(
        zone=zone,
        hotspot=hotspot,
        issue_type="local_hotspot",
        action_type="technical_check",
        target_devices=[],
        severity=local_status,
    )
    await _save_zone_action(ZoneAction(
        store_id=automation.store_id,
        zone_key=zone.key,
        zone_label=zone.label,
        temp_before=round(avg_temp, 2),
        ideal_min=zone.ideal_min,
        ideal_max=zone.ideal_max,
        direction="down",
        reason=reason,
        confidence=_confidence(hotspot.peak_temp, zone, local_status, 1),
        mode=automation.mode,
        status="suggestion",
        suggestion_signature=signature,
    ), session)


def _build_power_on_reason(
    avg: float,
    zone: ZoneConfig,
    status: str,
    device: Device,
    trend: float | None = None,
    hotspot: "Hotspot | None" = None,
) -> str:
    labels = {"WARM": "zona aquecendo", "HOT": "zona quente", "CRITICAL": "zona crítica"}
    label = labels.get(status, status)
    wall_note = (
        " [SALA_FECHADA — aparelho interno da sala usado.]"
        if zone.zone_type == "SALA_FECHADA" else ""
    )
    trend_note = f" Tendência {trend:+.1f}°C/h." if trend is not None else ""
    if hotspot and hotspot.has_coordinates and hotspot.contributing_names:
        hotspot_note = (
            f" Hotspot identificado próximo a {hotspot.contributing_names[0]} "
            f"({hotspot.peak_temp:.1f}°C); {device.name} selecionado por proximidade ao ponto quente."
        )
    else:
        hotspot_note = ""
    return (
        f"Temperatura média {avg:.1f}°C ({label}).{trend_note} "
        f"Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ligar {device.name} desligado para aumentar capacidade de resfriamento da zona.{wall_note}{hotspot_note}"
    )


def _build_reason(
    avg: float,
    zone: ZoneConfig,
    status: str,
    device: Device,
    direction: str,
    trend: float | None = None,
    hotspot: "Hotspot | None" = None,
) -> str:
    direction_pt = "reduzir" if direction == "down" else "aumentar"
    labels = {"WARM": "zona aquecendo", "HOT": "zona quente", "CRITICAL": "zona crítica", "COLD": "zona fria"}
    label = labels.get(status, status)
    wall_note = (
        " [SALA_FECHADA — aparelho interno da sala usado.]"
        if zone.zone_type == "SALA_FECHADA" else ""
    )
    trend_note = f" Tendência {trend:+.1f}°C/h." if trend is not None else ""
    step = _step_size(status)
    if hotspot and hotspot.has_coordinates and hotspot.contributing_names:
        hotspot_note = (
            f" Hotspot identificado próximo a {hotspot.contributing_names[0]} "
            f"({hotspot.peak_temp:.1f}°C); {device.name} selecionado por proximidade ao ponto quente."
        )
    else:
        hotspot_note = ""
    return (
        f"Temperatura média {avg:.1f}°C ({label}).{trend_note} "
        f"Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ajuste via {device.name} para {direction_pt} {step}°C no setpoint.{wall_note}{hotspot_note}"
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
