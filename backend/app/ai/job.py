"""
Job de análise de IA: roda após cada ciclo de polling.
Consulta devices com anomalias, envia ao Ollama para diagnóstico
e dispara emails para severidades HIGH/CRITICAL.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.models.store import Store, StoreSector

logger = logging.getLogger(__name__)

# Cooldown entre emails do mesmo device (evita spam)
EMAIL_COOLDOWN_SECONDS = 3600  # 1 hora

# Statuses que merecem análise
ANOMALOUS_STATUSES = {"ATENÇÃO", "CRÍTICO", "BAIXA_EFICIÊNCIA", "SEM_LEITURA", "DESLIGADO"}


async def run_ai_analysis() -> None:
    """Ponto de entrada do job — chamado após poll_all_devices."""
    if not settings.ai_analysis_enabled:
        return

    from app.ai.analyzer import analyze_anomalies
    from app.ai.email_manager import buffer_alert_for_email

    try:
        devices_data, device_info_map = await _fetch_anomalous_devices()
        if not devices_data:
            logger.debug("AI analysis: nenhuma anomalia para analisar")
            return

        logger.info("AI analysis: analisando %d dispositivos anômalos", len(devices_data))
        analyses = await analyze_anomalies(devices_data)

        alerts_buffered = 0
        for analysis in analyses:
            device_info = device_info_map.get(analysis.device_id, {})
            await _cache_analysis(analysis, device_info)

            if not analysis.email_worthy:
                continue

            cooldown_key = f"ai:email_cd:{analysis.device_id}"
            if await redis_client.exists(cooldown_key):
                logger.debug("Cooldown ativo para %s", analysis.device_name)
                continue

            await buffer_alert_for_email(analysis, device_info)
            await redis_client.set(cooldown_key, "1", ttl=EMAIL_COOLDOWN_SECONDS)
            alerts_buffered += 1

        logger.info(
            "AI analysis concluída: %d analisados, %d alertas adicionados ao buffer de email",
            len(analyses), alerts_buffered
        )
    except Exception as exc:
        logger.error("Erro no job de análise de IA: %s", exc, exc_info=True)


from sqlalchemy import select, func
from app.models.reading import DeviceReading

async def _fetch_anomalous_devices() -> tuple[list[dict], dict[str, dict]]:
    """Retorna lista de dicts enriquecidos para o LLM e um mapa device_id → info."""
    async with AsyncSessionLocal() as session:
        now   = datetime.utcnow()
        hour  = now.hour
        ago7d = now - timedelta(days=7)
        ago1h = now - timedelta(hours=1)
        ago30d = now - timedelta(days=30)

        # Média histórica na mesma hora (últimos 7 dias)
        baseline_res = await session.execute(
            select(DeviceReading.device_id, func.avg(DeviceReading.temperature).label("avg_temp"))
            .where(DeviceReading.time >= ago7d,
                   func.extract("hour", DeviceReading.time) == hour,
                   DeviceReading.temperature.is_not(None))
            .group_by(DeviceReading.device_id)
        )
        baseline_map = {str(r.device_id): r.avg_temp for r in baseline_res.all()}

        # Tendência: última leitura vs leitura de 1h atrás
        trend_res = await session.execute(
            select(
                DeviceReading.device_id,
                func.first_value(DeviceReading.temperature)
                    .over(partition_by=DeviceReading.device_id,
                          order_by=DeviceReading.time.desc()).label("temp_latest"),
                func.first_value(DeviceReading.temperature)
                    .over(partition_by=DeviceReading.device_id,
                          order_by=DeviceReading.time.asc()).label("temp_oldest"),
            )
            .where(DeviceReading.time >= ago1h,
                   DeviceReading.temperature.is_not(None))
            .distinct(DeviceReading.device_id)
        )
        trend_map: dict[str, tuple[float, float]] = {}
        for r in trend_res.all():
            if r.temp_latest is not None and r.temp_oldest is not None:
                trend_map[str(r.device_id)] = (r.temp_latest, r.temp_oldest)

        # Contagem de alertas nos últimos 30 dias
        alert_res = await session.execute(
            select(Alert.device_id, func.count(Alert.id).label("cnt"))
            .where(Alert.opened_at >= ago30d)
            .group_by(Alert.device_id)
        )
        alert_map = {str(r.device_id): r.cnt for r in alert_res.all()}

        # Query principal com campos enriquecidos
        result = await session.execute(
            select(
                Device.id,
                Device.name,
                Device.btu,
                Device.is_critical_environment,
                Device.last_maintenance,
                DeviceStatusLatest.status_classification,
                DeviceStatusLatest.temperature,
                DeviceStatusLatest.delta_temp,
                DeviceStatusLatest.humidity,
                DeviceStatusLatest.efficiency_score,
                DeviceStatusLatest.state,
                DeviceStatusLatest.updated_at,
                DeviceStatusLatest.accumulated_on_minutes,
                DeviceStatusLatest.accumulated_off_minutes,
                DeviceParameters.setpoint_cool,
                StoreSector.name.label("sector_name"),
                Store.name.label("store_name"),
            )
            .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .join(Store, StoreSector.store_id == Store.id)
            .outerjoin(DeviceParameters, Device.id == DeviceParameters.device_id)
            .where(Device.active == True,
                   DeviceStatusLatest.status_classification.in_(ANOMALOUS_STATUSES))
        )
        rows = result.all()

    devices_data: list[dict] = []
    device_info_map: dict[str, dict] = {}

    for row in rows:
        did = str(row.id)

        on_min  = row.accumulated_on_minutes
        off_min = row.accumulated_off_minutes
        hours_on = round(on_min / 60, 0) if on_min else None
        total_min = (on_min or 0) + (off_min or 0)
        uptime_pct = round(on_min / total_min * 100, 1) if total_min > 0 and on_min else None

        days_maint = None
        if row.last_maintenance:
            days_maint = (datetime.utcnow() - row.last_maintenance).days

        # Tendência de temperatura
        trend_label, trend_delta = None, None
        if did in trend_map:
            latest, oldest = trend_map[did]
            td = round(latest - oldest, 1)
            trend_delta = td
            if td > 0.5:
                trend_label = "subindo"
            elif td < -0.5:
                trend_label = "caindo"
            else:
                trend_label = "estável"

        info = {
            "device_id": did,
            "device_name": row.name,
            "store_name": row.store_name,
            "sector_name": row.sector_name,
            "status": row.status_classification,
            "temperature": row.temperature,
            "setpoint_cool": row.setpoint_cool or 24,
            "delta_temp": row.delta_temp,
            "humidity": row.humidity,
            "efficiency_score": row.efficiency_score,
            "state": row.state,
            "is_critical_environment": row.is_critical_environment,
            "btu": row.btu,
            "historical_avg": baseline_map.get(did),
            "temperature_trend": trend_label,
            "temperature_trend_delta": trend_delta,
            "hours_of_operation": hours_on,
            "uptime_pct": uptime_pct,
            "days_since_maintenance": days_maint,
            "alerts_30d": alert_map.get(did, 0),
            "last_reading_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        devices_data.append(info)
        device_info_map[did] = info

    return devices_data, device_info_map


async def _cache_analysis(analysis, device_info: dict) -> None:
    """Salva última análise no Redis para o endpoint /ai/status."""
    import json
    key = f"ai:last_analysis:{analysis.device_id}"
    payload = {
        **analysis.model_dump(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "temperature": device_info.get("temperature"),
        "setpoint_cool": device_info.get("setpoint_cool"),
        "store_name": device_info.get("store_name"),
        "sector_name": device_info.get("sector_name"),
    }
    await redis_client.set(key, json.dumps(payload), ttl=86400)  # 24h
