import logging
import uuid
from datetime import datetime
import asyncio
from sqlalchemy import func, select, update

logger = logging.getLogger(__name__)
from app.db.session import AsyncSessionLocal
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.models.alert import Alert
from app.brise.client import brise_client
from app.cache.device_cache import (
    get_device_params, set_device_params, set_device_status,
    check_alert_cooldown, set_alert_cooldown,
    acquire_polling_lock, release_polling_lock,
)
from app.cache.redis_client import redis_client
from app.rules.classifier import (
    NO_READING_THRESHOLD_MINUTES, classify_status,
    STATUS_NO_READING, STATUS_OFF, CONSECUTIVE_READINGS_REQUIRED,
)
from app.rules.alert_generator import generate_alert_if_needed

async def poll_device(
    device_id: uuid.UUID,
    brise_id: str,
    is_critical_env: bool,
    zone_ideal_min: float | None = None,
    zone_ideal_max: float | None = None,
):
    if not await acquire_polling_lock(device_id):
        return
    try:
        variables = await brise_client.get_variables(brise_id)
        async with AsyncSessionLocal() as session:
            status_row = await session.get(DeviceStatusLatest, device_id)
            params_result = await session.execute(
                select(DeviceParameters).where(DeviceParameters.device_id == device_id)
            )
            params_row = params_result.scalar_one_or_none()
            setpoint_cool = params_row.setpoint_cool if params_row else 24
            mode_ac = params_row.mode_ac if params_row else 0
            btu = 12000
            device = await session.get(Device, device_id)
            if device:
                btu = device.btu
            last_good_result = await session.execute(
                select(func.max(DeviceReading.time)).where(
                    DeviceReading.device_id == device_id,
                    DeviceReading.temperature.is_not(None),
                )
            )
            last_reading_time = last_good_result.scalar() or (
                status_row.updated_at if status_row and status_row.temperature is not None else None
            )
            consecutive_count = (status_row.consecutive_readings_count or 0) if status_row else 0
            current_status = status_row.status_classification if status_row else None
            prev_state = status_row.state if status_row else None

            if variables:
                prev_status = current_status
                status, delta, efficiency = classify_status(
                    state=variables.state,
                    temperature=variables.temperature,
                    setpoint_cool=setpoint_cool,
                    mode_ac=mode_ac,
                    btu=btu,
                    consumption_estimated=variables.consumptionEstimated,
                    last_reading_time=None,
                    consecutive_count=consecutive_count,
                    current_status=current_status,
                    zone_ideal_min=zone_ideal_min,
                    zone_ideal_max=zone_ideal_max,
                )
                if status == prev_status:
                    consecutive_count += 1
                elif prev_status in (STATUS_NO_READING, STATUS_OFF):
                    # Dispositivo voltou do offline — aciona alertas imediatamente
                    consecutive_count = CONSECUTIVE_READINGS_REQUIRED
                else:
                    consecutive_count = 1
            else:
                if (
                    last_reading_time
                    and (datetime.utcnow() - last_reading_time).total_seconds()
                    < NO_READING_THRESHOLD_MINUTES * 60
                ):
                    return

                status, delta, efficiency = classify_status(
                    state=None, temperature=None, setpoint_cool=setpoint_cool,
                    mode_ac=mode_ac, btu=btu, consumption_estimated=None,
                    last_reading_time=last_reading_time,
                    consecutive_count=consecutive_count,
                    current_status=current_status,
                    zone_ideal_min=zone_ideal_min,
                    zone_ideal_max=zone_ideal_max,
                )
                consecutive_count = 0

            if variables and prev_state is not None and variables.state != prev_state:
                cycling_key = f"device:cycling:{device_id}"
                count = await redis_client.incr(cycling_key)
                if count == 1:
                    await redis_client.expire(cycling_key, 3600)
                if count > 10:
                    status = "COMPRESSOR_CYCLING"
                    logger.warning("Device %s detectado como CICLANDO (%d trocas/hora)", device_id, count)

            on_min  = variables.ON  if variables else None
            off_min = variables.OFF if variables else None

            reading = DeviceReading(
                time=datetime.utcnow(),
                device_id=device_id,
                state=variables.state if variables else None,
                temperature=variables.temperature if variables else None,
                humidity=variables.humidity if variables else None,
                consumption=variables.consumption if variables else None,
                consumption_estimated=variables.consumptionEstimated if variables else None,
                status_classification=status,
                delta_temp=delta,
                efficiency_score=efficiency,
                accumulated_on_minutes=on_min,
                accumulated_off_minutes=off_min,
                raw_payload=variables.model_dump() if variables else None,
            )
            session.add(reading)

            if status_row:
                status_row.state = variables.state if variables else None
                status_row.temperature = variables.temperature if variables else None
                status_row.humidity = variables.humidity if variables else None
                status_row.consumption = variables.consumption if variables else None
                status_row.consumption_estimated = variables.consumptionEstimated if variables else None
                status_row.status_classification = status
                status_row.delta_temp = delta
                status_row.efficiency_score = efficiency
                status_row.consecutive_readings_count = consecutive_count
                if on_min is not None:
                    status_row.accumulated_on_minutes = on_min
                if off_min is not None:
                    status_row.accumulated_off_minutes = off_min
                status_row.updated_at = datetime.utcnow()
            else:
                new_status = DeviceStatusLatest(
                    device_id=device_id,
                    state=variables.state if variables else None,
                    temperature=variables.temperature if variables else None,
                    humidity=variables.humidity if variables else None,
                    consumption_estimated=variables.consumptionEstimated if variables else None,
                    status_classification=status,
                    delta_temp=delta,
                    efficiency_score=efficiency,
                    consecutive_readings_count=consecutive_count,
                    accumulated_on_minutes=on_min,
                    accumulated_off_minutes=off_min,
                    updated_at=datetime.utcnow(),
                )
                session.add(new_status)

            alert_data = generate_alert_if_needed(
                device_id=device_id,
                status=status,
                delta_temp=delta,
                temperature=variables.temperature if variables else None,
                setpoint_cool=setpoint_cool,
                is_critical_environment=is_critical_env,
                last_reading_time=last_reading_time,
            )
            if alert_data:
                alert_type = alert_data["alert_type"]
                in_cooldown = await check_alert_cooldown(device_id, alert_type)
                if not in_cooldown:
                    existing_open = await session.scalar(
                        select(Alert.id).where(
                            Alert.device_id == device_id,
                            Alert.alert_type == alert_type,
                            Alert.status == "OPEN",
                        ).limit(1)
                    )
                    if not existing_open:
                        session.add(Alert(**alert_data))
                    await set_alert_cooldown(device_id, alert_type, alert_data["severity"])

            await session.commit()

            cache_data = {
                "device_id": str(device_id),
                "brise_id": brise_id,
                "status": status,
                "temperature": variables.temperature if variables else None,
                "humidity": variables.humidity if variables else None,
                "delta_temp": delta,
                "efficiency_score": efficiency,
                "state": variables.state if variables else None,
                "updated_at": datetime.utcnow().isoformat(),
            }
            await set_device_status(device_id, cache_data)
            await redis_client.publish("device.reading.new", cache_data)
    finally:
        await release_polling_lock(device_id)

async def poll_all_devices():
    from app.models.store import StoreSector
    from app.services.zone_controller import ZONES

    # Mapa reverso: sector_name → (ideal_min, ideal_max)
    sector_to_zone: dict[str, tuple[float, float]] = {}
    for zone_cfg in ZONES.values():
        for sector_name in zone_cfg.sector_names:
            sector_to_zone[sector_name] = (zone_cfg.ideal_min, zone_cfg.ideal_max)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Device, StoreSector.name.label("sector_name"))
            .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
            .where(
                Device.active == True,
                Device.brise_device_id.not_like("MANUAL-%"),
                Device.source_url.is_(None),
            )
        )
        rows = result.all()

    tasks = []
    for device, sector_name in rows:
        zone_range = sector_to_zone.get(sector_name or "")
        tasks.append(poll_device(
            device.id,
            device.brise_device_id,
            device.is_critical_environment,
            zone_ideal_min=zone_range[0] if zone_range else None,
            zone_ideal_max=zone_range[1] if zone_range else None,
        ))
    devices = [row[0] for row in rows]
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for device, outcome in zip(devices, results):
            if isinstance(outcome, Exception):
                logger.error(
                    "poll_device falhou [%s]: %s: %s",
                    device.brise_device_id, type(outcome).__name__, outcome,
                )

    # Dispara análise de IA logo após o polling (non-blocking)
    from app.config import settings
    if settings.ai_analysis_enabled:
        from app.ai.job import run_ai_analysis
        asyncio.create_task(run_ai_analysis())
