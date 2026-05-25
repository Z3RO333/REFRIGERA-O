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
from app.cache.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.models.store import StoreSector
from app.models.zone import ZoneAction, ZoneAutomation
from app.services.thermal_spatial import DevicePoint, Hotspot, detect_hotspot, proximity_score

logger = logging.getLogger(__name__)

# Statuses que impedem comandos
BLOCKED_STATUSES = {"SEM_LEITURA", "AGUARDANDO_LEITURA", "DESLIGADO", "COMPRESSOR_CYCLING"}

# Cooldown entre execuções na mesma zona (segundos)
ZONE_COOLDOWN_SECONDS = 900  # 15 min

# Proteção por janela curta — evita rajadas sem bloquear o dia inteiro
DEVICE_WINDOW_SECONDS = 900      # janela de 15 min por device
DEVICE_WINDOW_MAX_CMDS = 4       # máximo de 4 comandos por device por janela

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
    # Se definido, a zona usa IDs de device em vez de nomes de setor (zonas personalizadas)
    device_ids: list[uuid.UUID] | None = None


# ── Zonas abertas (departamentos amplos) ──────────────────────────────────────
# Zonas hardcoded removidas — sistema usa apenas zonas customizadas criadas pelo operador.
# Manter dict vazio para compatibilidade com código que ainda importa ZONES.
ZONES: dict[str, ZoneConfig] = {}


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
        # Pré-carrega zonas customizadas para evitar N+1
        custom_zones = await _load_all_custom_zones(session)

    if not automations:
        return

    all_zones: dict[str, ZoneConfig] = custom_zones

    logger.info("Zone controller: avaliando %d zonas ativas", len(automations))
    for automation in automations:
        zone = all_zones.get(automation.zone_key)
        if not zone:
            logger.warning("Zona '%s' sem configuração — ignorando", automation.zone_key)
            continue
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
    """Passo de ajuste de setpoint: 2°C para zona crítica, 1°C nos demais casos."""
    return 2 if status == "CRITICAL" else 1


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

        # Fontes de temperatura: ACs ativos + sensores externos (exclui DND, status bloqueado)
        # Separação: sensores contribuem para avg_temp mas não recebem comandos
        temp_sources = [
            d for d in devices
            if d.status.temperature is not None
            and d.status.status_classification not in BLOCKED_STATUSES
            and not d.device.dnd
        ]

        # Fallback: ACs classificados como DESLIGADO mas ainda reportando temperatura.
        # Isso ocorre quando a API Brise retorna state=false transitoriamente para ACs ligados.
        # Nesse caso, usamos a temperatura disponível e tentamos ligar os ACs, mas sem
        # enviar comandos de setpoint (readable vazio).
        if not temp_sources:
            off_with_temp = [
                d for d in devices
                if not d.device.source_url
                and not d.device.dnd
                and d.status.temperature is not None
                and d.status.status_classification == "DESLIGADO"
            ]
            if off_with_temp:
                temp_sources = off_with_temp
            readable = []
        else:
            # Ajustáveis via comando: apenas ACs (sensores externos têm source_url)
            readable = [d for d in temp_sources if not d.device.source_url]

        if not temp_sources:
            # Sem leitura térmica disponível — diagnóstico detalhado com rate-limit anti-spam
            ac_devices = [d for d in devices if not d.device.source_url and not d.device.dnd]
            n_total = len(ac_devices)
            n_off = sum(1 for d in ac_devices if d.status.status_classification == "DESLIGADO")
            n_waiting = sum(1 for d in ac_devices if d.status.status_classification == "AGUARDANDO_LEITURA")
            n_no_comm = sum(1 for d in ac_devices if d.status.status_classification == "SEM_LEITURA")
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

        if status == "COMFORT":
            # Zona confortável mas aquecendo rapidamente → suggestion preemptiva
            if trend is not None and trend > 2.5:
                await _log_trending(automation, zone, avg_temp, trend, session)
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

        power_on_candidate = _select_power_on_candidate(devices, params_map, hotspot=hotspot) if direction == "down" else None
        if power_on_candidate is not None:
            power_device, power_params = power_on_candidate
            confidence = _confidence(avg_temp, zone, status, max(len(readable), 1))
            reason = _build_power_on_reason(avg_temp, zone, status, power_device.device, trend, hotspot=hotspot)
            setpoint_before = power_params.setpoint_cool
            action_status = "suggestion"
            block_reason = None

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
                    ok, _api_ms = await _execute_power_on(power_device.device, power_params, session)
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

            _power_api_ms = locals().get("_api_ms", None)
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
                setpoint_after=setpoint_before,
                reason=reason,
                confidence=confidence,
                mode=automation.mode,
                status=action_status,
                block_reason=block_reason,
                decision_ms=int((time.monotonic() - _t0) * 1000) if action_status == "pending_verification" else None,
                api_ms=_power_api_ms if action_status == "pending_verification" else None,
            )
            session.add(action)
            await session.commit()

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
                "setpoint_after": setpoint_before,
                "action": "power_on",
            })
            return

        # Seleciona melhor device (com verificação de headroom de setpoint)
        best = _select_best_device(readable, status, params_map, direction, automation.setpoint_min, automation.setpoint_max, hotspot=hotspot)
        if best is None:
            reason = _build_no_adjustable_reason(
                readable, devices, params_map, direction,
                automation.setpoint_min, automation.setpoint_max, zone,
            )
            await _log_blocked(automation, zone, avg_temp, reason, session)
            return

        best_device, best_params = best
        new_setpoint = best_params.setpoint_cool + (step if direction == "up" else -step)

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
        reason = _build_reason(avg_temp, zone, status, best_device.device, direction, trend, hotspot=hotspot)

        # Captura ANTES de _execute_setpoint modificar params.setpoint_cool
        setpoint_before = best_params.setpoint_cool

        action_status = "suggestion"
        block_reason = None

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
            ok, _api_ms = await _execute_setpoint(best_device.device, best_params, direction, automation, session, step=step)
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

        _setpoint_api_ms = locals().get("_api_ms", None)
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
            decision_ms=int((time.monotonic() - _t0) * 1000) if action_status == "pending_verification" else None,
            api_ms=_setpoint_api_ms if action_status == "pending_verification" else None,
        )
        session.add(action)
        await session.commit()

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


async def _get_zone_devices(
    store_id: uuid.UUID, zone: ZoneConfig, session: AsyncSession
) -> tuple[list[_DeviceRow], dict[uuid.UUID, DeviceParameters]]:
    if zone.device_ids is not None:
        # Zona personalizada: filtra por IDs de device
        if not zone.device_ids:
            return [], {}
        result = await session.execute(
            select(Device, DeviceStatusLatest)
            .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .where(Device.active == True, Device.id.in_(zone.device_ids))
        )
    else:
        # Zona padrão: filtra por nomes de setor
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
    direction: str,
    setpoint_min: int,
    setpoint_max: int,
    hotspot: "Hotspot | None" = None,
) -> tuple[_DeviceRow, DeviceParameters] | None:
    going_down = direction == "down"
    candidates = [
        r for r in readable
        if r.device.id in params_map
        and not r.device.source_url
        # Headroom: device must have room to move in the desired direction
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


def _select_power_on_candidate(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    hotspot: "Hotspot | None" = None,
) -> tuple[_DeviceRow, DeviceParameters] | None:
    candidates = []
    for row in devices:
        if row.device.dnd or row.device.source_url:
            continue
        params = params_map.get(row.device.id)
        is_off = (
            row.status.status_classification == "DESLIGADO"
            or row.status.state is False
            or (params is not None and params.mode_device == 0)
        )
        if is_off:
            candidates.append(row)

    if not candidates:
        return None

    candidates.sort(
        key=lambda row: (
            proximity_score(
                row.device.position_x,
                row.device.position_y,
                hotspot=hotspot,
                influence_radius_m=float(row.device.influence_radius_m or 8),
            ),
            row.device.btu or 0,
            row.device.name or "",
        ),
        reverse=True,
    )
    best = candidates[0]
    # Se não há params, cria um objeto temporário com defaults seguros para ligar
    params = params_map.get(best.device.id)
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
) -> tuple[bool, int]:
    brise_params = {
        "modeDevice": 1,
        "modeAC": 0,
        "fanSpeed": params.fan_speed or 1,
        "setpointCool": params.setpoint_cool or 22,
        "setpointHeat": params.setpoint_heat or 28,
        "ecoCool": params.eco_cool or False,
        "ecoHeat": params.eco_heat or False,
    }

    _t_api = time.monotonic()
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    _api_ms = int((time.monotonic() - _t_api) * 1000)
    if success:
        params.mode_device = 1
        params.mode_ac = 0
        params.synced_at = datetime.utcnow()
        # Persiste o params se for novo (sem pk — device sem histórico de configuração)
        if params.id is None:
            session.add(params)
        if device.status_latest:
            device.status_latest.state = True
            device.status_latest.updated_at = datetime.utcnow()
        await session.commit()
    return success, _api_ms


async def _execute_setpoint(
    device: Device,
    params: DeviceParameters,
    direction: str,
    automation: ZoneAutomation,
    session: AsyncSession,
    step: int = 1,
) -> tuple[bool, int]:
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

    brise_params = {
        "modeDevice": 1,
        "modeAC": 0,
        "fanSpeed": params.fan_speed,
        "setpointCool": new_setpoint,
        "setpointHeat": params.setpoint_heat,
        "ecoCool": params.eco_cool,
        "ecoHeat": params.eco_heat,
    }

    _t_api = time.monotonic()
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    _api_ms = int((time.monotonic() - _t_api) * 1000)
    if success:
        params.setpoint_cool = new_setpoint
        params.synced_at = datetime.utcnow()
        await session.commit()
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
        async with redis_client.client.pipeline(transaction=False) as pipe:
            await pipe.incr(key)
            await pipe.expire(key, DEVICE_WINDOW_SECONDS)
            results = await pipe.execute()
        count = results[0]
        return count <= DEVICE_WINDOW_MAX_CMDS
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
