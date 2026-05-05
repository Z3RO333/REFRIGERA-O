"""
Job de análise de IA: roda após cada ciclo de polling.
Consulta devices com anomalias, envia ao Ollama para diagnóstico
e dispara emails para severidades HIGH/CRITICAL.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
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
    """Retorna lista de dicts para o LLM e um mapa device_id → info."""
    async with AsyncSessionLocal() as session:
        # Busca a média histórica (últimos 7 dias) por dispositivo no mesmo horário
        now = datetime.utcnow()
        hour = now.hour
        window_start = now - timedelta(days=7)
        historical_baseline = await session.execute(
            select(DeviceReading.device_id, func.avg(DeviceReading.temperature).label("avg_temp"))
            .where(
                DeviceReading.time >= window_start,
                func.extract('hour', DeviceReading.time) == hour,
                DeviceReading.temperature.is_not(None),
            )
            .group_by(DeviceReading.device_id)
        )
        baseline_map = {str(r.device_id): r.avg_temp for r in historical_baseline.all()}

        result = await session.execute(
            select(
                Device.id,
                Device.name,
                Device.btu,
                Device.is_critical_environment,
                DeviceStatusLatest.status_classification,
                DeviceStatusLatest.temperature,
                DeviceStatusLatest.delta_temp,
                DeviceStatusLatest.humidity,
                DeviceStatusLatest.efficiency_score,
                DeviceStatusLatest.state,
                DeviceStatusLatest.updated_at,
                DeviceParameters.setpoint_cool,
                StoreSector.name.label("sector_name"),
                Store.name.label("store_name"),
            )
            .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .join(Store, StoreSector.store_id == Store.id)
            .outerjoin(DeviceParameters, Device.id == DeviceParameters.device_id)
            .where(
                Device.active == True,
                DeviceStatusLatest.status_classification.in_(ANOMALOUS_STATUSES),
            )
        )
        rows = result.all()

    devices_data: list[dict] = []
    device_info_map: dict[str, dict] = {}

    for row in rows:
        did = str(row.id)
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
