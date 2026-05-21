"""
Digital Twin Operacional — SISTEMA DE REFRIGERAÇÃO

Calcula, por zona, estado atual + tendência térmica + previsões + simulações heurísticas.
Operação em modo leitura/sugestão — NÃO executa comandos reais.

Fontes de dados (on-demand, sem persistência):
  - device_status_latest  → estado atual
  - device_readings       → histórico recente para tendência
  - ZONES (zone_controller) → configuração de zonas
"""
import logging
import uuid
from datetime import datetime, timedelta
from statistics import mean, stdev

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.services.zone_controller import BLOCKED_STATUSES, ZONES, ZoneConfig, _classify, _load_all_custom_zones

logger = logging.getLogger(__name__)

TREND_WINDOW_MINUTES = 90       # janela de histórico para tendência
TREND_MIN_POINTS = 3            # pontos mínimos para calcular regressão
STALE_THRESHOLD_MINUTES = 20    # leitura velha após este intervalo


# ── Funções puras ──────────────────────────────────────────────────────────────

def _slope_c_per_hour(points: list[tuple[float, float]]) -> float | None:
    """Regressão linear OLS sobre (x=minutos, y=°C). Retorna °C/hora ou None."""
    n = len(points)
    if n < 2:
        return None
    sx  = sum(x for x, _ in points)
    sy  = sum(y for _, y in points)
    sxy = sum(x * y for x, y in points)
    sx2 = sum(x * x for x, _ in points)
    denom = n * sx2 - sx * sx
    if abs(denom) < 1e-9:
        return None
    return round((n * sxy - sx * sy) / denom * 60, 2)  # °C/min → °C/hora


def _predict(base: float, trend_per_hour: float | None, minutes: float) -> float | None:
    if trend_per_hour is None:
        return None
    raw = base + trend_per_hour * (minutes / 60)
    return round(max(14.0, min(46.0, raw)), 1)


def _risk_level(status: str, trend: float | None) -> str:
    t = trend or 0.0
    if status == "NO_READING":
        return "LOW"
    if status == "COLD":
        return "MEDIUM"
    if status == "COMFORT":
        if t > 3.0:  return "HIGH"    # aquecimento muito rápido em zona confortável
        if t > 1.5:  return "MEDIUM"
        return "LOW"
    if status == "WARM":
        if t > 2.0:  return "HIGH"
        if t < -1.0: return "LOW"     # WARM mas resfriando — tendência favorável
        return "MEDIUM"
    if status == "HOT":
        return "CRITICAL" if t > 1.5 else "HIGH"
    if status == "CRITICAL":
        return "CRITICAL"
    return "LOW"


def _confidence_score(
    device_count: int,
    reading_count: int,
    freshness_ok: bool,
    variance: float | None,
    zone_type: str,
) -> float:
    cnt_score   = min(device_count  / 3.0,  1.0)
    hist_score  = min(reading_count / 12.0, 1.0)   # 12 pts ≈ 60 min a 5-min polling
    fresh_score = 1.0 if freshness_ok else 0.5
    var_score   = max(0.3, 1.0 - min((variance or 0) / 4.0, 0.7))
    base = cnt_score * 0.35 + hist_score * 0.30 + fresh_score * 0.20 + var_score * 0.15
    if zone_type == "SALA_FECHADA" and device_count < 2:
        base *= 0.75
    return round(base, 2)


def _simulate(
    current: float,
    trend: float | None,
    action: str,
    ideal_min: float,
    ideal_max: float,
    active_ac: int,
    zone_type: str,
    has_internal: bool,
) -> dict:
    """
    Heurística conservadora:
    - Cada AC ativo entrega ~0.5°C/h de capacidade de correção térmica.
    - Efeito limitado a 3 ACs (diminishing returns além disso).
    - SALA_FECHADA sem dispositivo interno → simulação bloqueada.
    """
    t = trend or 0.0
    capacity = min(active_ac, 3) * 0.5  # °C/hora de correção por ação

    if action == "no_action":
        adj = t
        label = "Sem ajuste — evolução natural"
        feasible = True
        block = None

    elif action == "setpoint_down_1":
        adj = t - capacity
        label = f"Reduzir setpoint −1°C ({active_ac} AC(s))"
        if active_ac == 0:
            feasible, block = False, "Nenhum AC ativo na zona."
        elif zone_type == "SALA_FECHADA" and not has_internal:
            feasible, block = False, "SALA_FECHADA sem dispositivo interno — ajuste externo ineficaz."
        else:
            feasible, block = True, None

    elif action == "setpoint_up_1":
        adj = t + capacity
        label = f"Aumentar setpoint +1°C ({active_ac} AC(s))"
        if active_ac == 0:
            feasible, block = False, "Nenhum AC ativo na zona."
        elif zone_type == "SALA_FECHADA" and not has_internal:
            feasible, block = False, "SALA_FECHADA sem dispositivo interno — ajuste externo ineficaz."
        else:
            feasible, block = True, None

    else:
        return {"action": action, "feasible": False, "block_reason": "Ação desconhecida."}

    p30 = _predict(current, adj, 30)
    p60 = _predict(current, adj, 60)
    s30 = _classify(p30, ideal_min, ideal_max) if p30 is not None else "NO_READING"
    s60 = _classify(p60, ideal_min, ideal_max) if p60 is not None else "NO_READING"

    return {
        "action": action,
        "label": label,
        "predicted_temp_30m": p30 if feasible else None,
        "predicted_temp_60m": p60 if feasible else None,
        "status_30m": s30 if feasible else "NO_READING",
        "status_60m": s60 if feasible else "NO_READING",
        "risk_after_30m": _risk_level(s30, None) if feasible else "LOW",
        "feasible": feasible,
        "block_reason": block,
    }


def _recommendation(
    status: str,
    trend: float | None,
    risk: str,
    ideal_min: float,
    ideal_max: float,
    current: float | None,
    predicted_30m: float | None,
    active_ac: int,
) -> tuple[str, str]:
    t = trend or 0.0
    temp = f"{current:.1f}°C" if current is not None else "desconhecida"
    p30  = f"{predicted_30m:.1f}°C" if predicted_30m is not None else "?"

    if status == "NO_READING":
        return "MONITOR", "Sem leituras disponíveis. Verifique conectividade dos sensores."

    if status == "COLD":
        return (
            "SETPOINT_UP",
            f"Zona fria ({temp}, ideal ≥ {ideal_min}°C). "
            f"Risco de superesfriamento. Aumentar setpoint em 1°C nos {active_ac} AC(s).",
        )

    if status == "COMFORT":
        if risk == "MEDIUM":
            return (
                "MONITOR",
                f"Zona confortável ({temp}) mas aquecendo a {t:+.1f}°C/h. "
                f"Previsão 30 min: {p30}. Considere antecipar ajuste.",
            )
        return "NONE", f"Zona confortável ({temp}), tendência {t:+.1f}°C/h. Nenhuma ação necessária."

    if status == "WARM":
        if t > 1.5:
            return (
                "SETPOINT_DOWN",
                f"Zona aquecendo ({temp}, {t:+.1f}°C/h — acelerada). "
                f"Previsão 30 min: {p30}. Reduzir setpoint agora nos {active_ac} AC(s).",
            )
        return (
            "SETPOINT_DOWN",
            f"Zona levemente aquecida ({temp}, {t:+.1f}°C/h). "
            f"Previsão 30 min: {p30}. Reduzir setpoint em 1°C nos {active_ac} AC(s).",
        )

    if status == "HOT":
        return (
            "SETPOINT_DOWN",
            f"Zona QUENTE ({temp}, ideal ≤ {ideal_max}°C, tendência {t:+.1f}°C/h). "
            f"Previsão 30 min: {p30}. Redução imediata nos {active_ac} AC(s). "
            f"Sem efeito em 15 min → acionar manutenção.",
        )

    if status == "CRITICAL":
        return (
            "SETPOINT_DOWN",
            f"TEMPERATURA CRÍTICA ({temp})! Muito acima da faixa ideal. "
            f"Tendência {t:+.1f}°C/h. Redução urgente em TODOS os {active_ac} AC(s). "
            f"Verificar filtros, carga térmica e equipamentos.",
        )

    return "MONITOR", f"Status {status} detectado ({temp}). Monitorar."


# ── Core: twin de uma zona ─────────────────────────────────────────────────────

async def compute_zone_twin(
    store_id: uuid.UUID,
    zone: ZoneConfig,
    session: AsyncSession,
) -> dict:
    from app.models.store import StoreSector

    now = datetime.utcnow()
    stale_cut = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)

    # ── 1. Estado atual ───────────────────────────────────────────────────────
    if zone.device_ids is not None:
        if not zone.device_ids:
            rows = []
        else:
            result = await session.execute(
                select(Device, DeviceStatusLatest)
                .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
                .where(Device.active == True, Device.id.in_(zone.device_ids))
            )
            rows = result.all()
    else:
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
    contributing: list[dict] = []
    device_ids: list[uuid.UUID] = []
    temps_now: list[float] = []
    active_ac = 0
    has_internal = False
    readings_fresh = True

    for device, status in rows:
        is_ext = device.source_url is not None
        device_ids.append(device.id)

        if not is_ext:
            has_internal = True
            if (
                status.status_classification not in BLOCKED_STATUSES
                and status.status_classification is not None
            ):
                active_ac += 1

        if status.temperature is not None:
            temps_now.append(float(status.temperature))

        if status.updated_at and status.updated_at < stale_cut:
            readings_fresh = False

        contributing.append({
            "device_id": str(device.id),
            "brise_id": device.brise_device_id,
            "name": device.name,
            "temperature": status.temperature,
            "status": status.status_classification or "UNKNOWN",
            "is_external_sensor": is_ext,
            "efficiency_score": status.efficiency_score,
            "updated_at": status.updated_at.isoformat() if status.updated_at else None,
        })

    current_avg: float | None = round(mean(temps_now), 2) if temps_now else None
    current_status = _classify(current_avg, zone.ideal_min, zone.ideal_max) if current_avg is not None else "NO_READING"

    variance: float | None = None
    if len(temps_now) >= 2:
        try:
            variance = round(stdev(temps_now) ** 2, 2)
        except Exception:
            pass

    # ── 2. Tendência histórica ─────────────────────────────────────────────────
    trend_per_hour: float | None = None
    hist_count = 0

    if device_ids:
        cutoff = now - timedelta(minutes=TREND_WINDOW_MINUTES)
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
        hist_count = len(hist_rows)

        if hist_count >= TREND_MIN_POINTS:
            # Agrupa em buckets de 5 min (intervalo do polling)
            buckets: dict[int, list[float]] = {}
            for t_row, temp in hist_rows:
                b = int((t_row - cutoff).total_seconds() / 300)
                buckets.setdefault(b, []).append(float(temp))

            bucket_pts = sorted(
                [(b * 5.0, mean(ts)) for b, ts in buckets.items()]
            )
            if len(bucket_pts) >= 2:
                trend_per_hour = _slope_c_per_hour(bucket_pts)

    # ── 3. Previsões ──────────────────────────────────────────────────────────
    p15 = _predict(current_avg, trend_per_hour, 15)  if current_avg is not None else None
    p30 = _predict(current_avg, trend_per_hour, 30)  if current_avg is not None else None
    p60 = _predict(current_avg, trend_per_hour, 60)  if current_avg is not None else None

    # ── 4. Risco, confiança e alerta preemptivo ───────────────────────────────
    risk = _risk_level(current_status, trend_per_hour)
    confidence = _confidence_score(len(temps_now), hist_count, readings_fresh, variance, zone.zone_type)
    # early_warning: zona OK agora mas em rota de colisão com o limite
    early_warning = (
        current_status == "COMFORT"
        and trend_per_hour is not None
        and trend_per_hour > 2.5
    )

    # ── 5. Recomendação ───────────────────────────────────────────────────────
    rec_action, explanation = _recommendation(
        current_status, trend_per_hour, risk,
        zone.ideal_min, zone.ideal_max, current_avg, p30, active_ac,
    )

    # ── 6. Simulações (somente quando há temperatura atual) ────────────────────
    simulations: list[dict] = []
    if current_avg is not None:
        for act in ("no_action", "setpoint_down_1", "setpoint_up_1"):
            simulations.append(
                _simulate(
                    current_avg, trend_per_hour, act,
                    zone.ideal_min, zone.ideal_max,
                    active_ac, zone.zone_type, has_internal,
                )
            )

    return {
        "store_id": str(store_id),
        "zone_key": zone.key,
        "zone_label": zone.label,
        "zone_type": zone.zone_type,
        "ideal_min": zone.ideal_min,
        "ideal_max": zone.ideal_max,
        "current_avg_temp": current_avg,
        "current_status": current_status,
        "trend_c_per_hour": trend_per_hour,
        "predicted_temp_15m": p15,
        "predicted_temp_30m": p30,
        "predicted_temp_60m": p60,
        "risk_level": risk,
        "confidence": confidence,
        "early_warning": early_warning,
        "contributing_devices": contributing,
        "recommended_action": rec_action,
        "explanation": explanation,
        "simulated_actions": simulations,
        "computed_at": now.isoformat(),
    }


async def compute_store_twin(store_id: uuid.UUID, session: AsyncSession) -> list[dict]:
    """Retorna digital twin de todas as zonas configuradas para a loja."""
    results = []
    from app.models.custom_zone import CustomZone

    custom_zones = await _load_all_custom_zones(session)
    custom_keys_res = await session.execute(select(CustomZone.zone_key).where(CustomZone.store_id == store_id))
    custom_keys = {row[0] for row in custom_keys_res.all()}
    all_zones = {**ZONES, **{k: v for k, v in custom_zones.items() if k in custom_keys}}

    for zone in all_zones.values():
        try:
            twin = await compute_zone_twin(store_id, zone, session)
            results.append(twin)
        except Exception as exc:
            logger.error("Erro twin zona %s: %s", zone.key, exc, exc_info=True)
    return results
