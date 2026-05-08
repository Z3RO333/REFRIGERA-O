import uuid
from datetime import datetime
import asyncio
from sqlalchemy import func, select, update
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
from app.rules.classifier import NO_READING_THRESHOLD_MINUTES, classify_status
from app.rules.alert_generator import generate_alert_if_needed

async def poll_device(device_id: uuid.UUID, brise_id: str, is_critical_env: bool):
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

            if variables:
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
                )
                if status == current_status:
                    consecutive_count += 1
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
                )
                consecutive_count = 0

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

            # Detecção de compressor ciclando (troca de estado excessiva)
            if variables and status_row and variables.state != status_row.state:
                cycling_key = f"device:cycling:{device_id}"
                # Incrementa contador de trocas de estado (expira em 1h)
                count = await redis_client.incr(cycling_key)
                if count == 1:
                    await redis_client.expire(cycling_key, 3600)

                # Se mudou de estado mais de 10 vezes em 1 hora, força status de CICLANDO
                if count > 10:
                    status = "COMPRESSOR_CYCLING"
                    logger.warning(f"Device {device_id} detectado como CICLANDO ({count} trocas/hora)")

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
                    alert = Alert(**alert_data)
                    session.add(alert)
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
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Device).where(
                Device.active == True,
                Device.brise_device_id.not_like("MANUAL-%"),
            )
        )
        devices = result.scalars().all()
    tasks = [
        poll_device(d.id, d.brise_device_id, d.is_critical_environment)
        for d in devices
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # Dispara análise de IA logo após o polling (non-blocking)
    from app.config import settings
    if settings.ai_analysis_enabled:
        from app.ai.job import run_ai_analysis
        asyncio.create_task(run_ai_analysis())
