import logging
import uuid
from datetime import datetime, timedelta
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
    STATUS_NO_READING, STATUS_STALE_READING, STATUS_OFF, CONSECUTIVE_READINGS_REQUIRED,
)
from app.rules.alert_generator import generate_alert_if_needed

TRANSIENT_RESTORE_MAX_AGE_HOURS = 24


def _latest_status_needs_restore(status_row: DeviceStatusLatest | None) -> bool:
    if status_row is None:
        return True
    return status_row.status_classification == STATUS_NO_READING or status_row.temperature is None


def _apply_last_good_reading_to_status(
    status_row: DeviceStatusLatest,
    last_good: DeviceReading,
    poll_error: str,
    now: datetime,
) -> None:
    status_row.state = last_good.state
    status_row.temperature = last_good.temperature
    status_row.humidity = last_good.humidity
    status_row.consumption = last_good.consumption
    status_row.consumption_estimated = last_good.consumption_estimated
    status_row.status_classification = STATUS_STALE_READING
    status_row.delta_temp = last_good.delta_temp
    status_row.efficiency_score = last_good.efficiency_score
    status_row.consecutive_readings_count = max(status_row.consecutive_readings_count or 0, 1)
    status_row.accumulated_on_minutes = last_good.accumulated_on_minutes
    status_row.accumulated_off_minutes = last_good.accumulated_off_minutes
    status_row.updated_at = last_good.time
    status_row.last_success_at = status_row.last_success_at or last_good.time
    status_row.last_error = poll_error
    status_row.last_error_at = now
    status_row.consecutive_failures = (status_row.consecutive_failures or 0) + 1


async def _restore_latest_status_from_history(
    session,
    device_id: uuid.UUID,
    status_row: DeviceStatusLatest | None,
    poll_error: str,
    now: datetime,
) -> tuple[DeviceStatusLatest | None, DeviceReading | None]:
    cutoff = now - timedelta(hours=TRANSIENT_RESTORE_MAX_AGE_HOURS)
    last_good_result = await session.execute(
        select(DeviceReading)
        .where(
            DeviceReading.device_id == device_id,
            DeviceReading.temperature.is_not(None),
            DeviceReading.status_classification.is_not(None),
            DeviceReading.status_classification != STATUS_NO_READING,
            DeviceReading.status_classification != STATUS_STALE_READING,
            DeviceReading.time >= cutoff,
        )
        .order_by(DeviceReading.time.desc())
        .limit(1)
    )
    last_good = last_good_result.scalar_one_or_none()
    if last_good is None:
        return status_row, None

    if status_row is None:
        status_row = DeviceStatusLatest(device_id=device_id)
        session.add(status_row)

    _apply_last_good_reading_to_status(status_row, last_good, poll_error, now)
    return status_row, last_good

async def poll_device(
    device_id: uuid.UUID,
    brise_id: str,
    is_critical_env: bool,
    zone_ideal_min: float | None = None,
    zone_ideal_max: float | None = None,
):
    if not await acquire_polling_lock(device_id):
        return
    poll_error: str | None = None  # definido antes do try para evitar NameError
    try:
        try:
            variables = await brise_client.get_variables(brise_id)
            if variables is None:
                poll_error = "API retornou resposta vazia (dispositivo offline ou sem comunicação)"
        except Exception as exc:
            variables = None
            err_str = str(exc)
            if "timeout" in err_str.lower() or "TimeoutError" in type(exc).__name__:
                poll_error = f"Timeout na API Brise ({type(exc).__name__})"
            elif "Connect" in type(exc).__name__ or "connection" in err_str.lower():
                poll_error = f"Falha de conexão com a API Brise"
            elif "RetryError" in type(exc).__name__ or "RetryError" in err_str:
                poll_error = f"Falha transitória na API Brise após retentativas ({type(exc).__name__})"
            elif "401" in err_str:
                poll_error = "Erro de autenticação na API Brise (401)"
            elif "403" in err_str:
                poll_error = "Acesso negado pela API Brise (403)"
            else:
                poll_error = f"Erro inesperado: {err_str[:120]}"
            logger.warning("poll_device [%s/%s] falhou: %s", brise_id, device_id, poll_error)

        # A chamada de rede para /parameters não pode segurar conexão do banco aberta.
        remote_params = None
        try:
            remote_params = await brise_client.get_parameters(brise_id)
        except Exception as exc:
            logger.warning("get_parameters durante polling [%s/%s] falhou: %s", brise_id, device_id, exc)

        async with AsyncSessionLocal() as session:
            status_row = await session.get(DeviceStatusLatest, device_id)
            params_result = await session.execute(
                select(DeviceParameters).where(DeviceParameters.device_id == device_id)
            )
            params_row = params_result.scalar_one_or_none()

            # A Brise é a fonte de verdade para setpoint atual. DeviceParameters é cache.
            if remote_params:
                if params_row is None:
                    params_row = DeviceParameters(device_id=device_id)
                    session.add(params_row)
                params_row.mode_device = remote_params.modeDevice if remote_params.modeDevice is not None else params_row.mode_device
                params_row.mode_ac = remote_params.modeAC if remote_params.modeAC is not None else params_row.mode_ac
                params_row.fan_speed = remote_params.fanSpeed if remote_params.fanSpeed is not None else params_row.fan_speed
                params_row.setpoint_cool = remote_params.setpointCool if remote_params.setpointCool is not None else params_row.setpoint_cool
                params_row.setpoint_heat = remote_params.setpointHeat if remote_params.setpointHeat is not None else params_row.setpoint_heat
                params_row.eco_cool = remote_params.ecoCool if remote_params.ecoCool is not None else params_row.eco_cool
                params_row.eco_heat = remote_params.ecoHeat if remote_params.ecoHeat is not None else params_row.eco_heat
                params_row.synced_at = datetime.utcnow()

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
            transient_api_error = bool(
                poll_error
                and (
                    "transitória" in poll_error
                    or "Timeout" in poll_error
                    or "conexão" in poll_error
                )
            )

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
                if transient_api_error:
                    now = datetime.utcnow()
                    restored_reading = None
                    if _latest_status_needs_restore(status_row):
                        status_row, restored_reading = await _restore_latest_status_from_history(
                            session,
                            device_id,
                            status_row,
                            poll_error,
                            now,
                        )
                    elif status_row is not None:
                        status_row.last_error = poll_error
                        status_row.last_error_at = now
                        status_row.consecutive_failures = (status_row.consecutive_failures or 0) + 1

                    if status_row is not None:
                        await session.commit()
                        if restored_reading is not None:
                            logger.warning(
                                "poll_device [%s/%s]: Brise instável; restaurando latest com última leitura boa de %s",
                                brise_id,
                                device_id,
                                restored_reading.time.isoformat(),
                            )
                            cache_data = {
                                "device_id": str(device_id),
                                "brise_id": brise_id,
                                "status": status_row.status_classification,
                                "temperature": status_row.temperature,
                                "humidity": status_row.humidity,
                                "delta_temp": status_row.delta_temp,
                                "efficiency_score": status_row.efficiency_score,
                                "state": status_row.state,
                                "setpoint_cool": setpoint_cool,
                                "current_setpoint": setpoint_cool,
                                "setpoint_synced_at": params_row.synced_at.isoformat() if params_row and params_row.synced_at else None,
                                "setpoint_source": "brise_parameters_cache" if params_row else "default",
                                "updated_at": status_row.updated_at.isoformat() if status_row.updated_at else now.isoformat(),
                                "telemetry_stale": True,
                                "last_error": poll_error,
                            }
                            await set_device_status(device_id, cache_data)
                            await redis_client.publish("device.reading.new", cache_data)
                    return

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

            now = datetime.utcnow()
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
                status_row.updated_at = now
                # Diagnóstico
                if variables and variables.temperature is not None:
                    status_row.last_success_at = now
                    status_row.consecutive_failures = 0
                    status_row.last_error = None
                elif poll_error:
                    status_row.last_error = poll_error
                    status_row.last_error_at = now
                    status_row.consecutive_failures = (status_row.consecutive_failures or 0) + 1
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
                    consecutive_failures=1 if poll_error else 0,
                    last_error=poll_error,
                    last_error_at=datetime.utcnow() if poll_error else None,
                    last_success_at=datetime.utcnow() if not poll_error else None,
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
                "setpoint_cool": setpoint_cool,
                "current_setpoint": setpoint_cool,
                "setpoint_synced_at": params_row.synced_at.isoformat() if params_row and params_row.synced_at else None,
                "setpoint_source": "brise_parameters_cache" if params_row else "default",
                "updated_at": datetime.utcnow().isoformat(),
            }
            await set_device_status(device_id, cache_data)
            if params_row:
                await set_device_params(device_id, {
                    "mode_device": params_row.mode_device,
                    "mode_ac": params_row.mode_ac,
                    "fan_speed": params_row.fan_speed,
                    "setpoint_cool": params_row.setpoint_cool,
                    "setpoint_heat": params_row.setpoint_heat,
                    "eco_cool": params_row.eco_cool,
                    "eco_heat": params_row.eco_heat,
                    "synced_at": params_row.synced_at.isoformat() if params_row.synced_at else None,
                    "source": "brise_api" if remote_params else "db_cache",
                })
            await redis_client.publish("device.reading.new", cache_data)
    finally:
        await release_polling_lock(device_id)

async def poll_all_devices():
    from app.models.store import StoreSector
    from app.models.custom_zone import CustomZone, CustomZoneDevice

    async with AsyncSessionLocal() as session:
        # Mapa device_id → (ideal_min, ideal_max) via zonas customizadas ativas
        zone_range_result = await session.execute(
            select(CustomZoneDevice.device_id, CustomZone.ideal_min, CustomZone.ideal_max)
            .join(CustomZone, CustomZoneDevice.zone_id == CustomZone.id)
            .where(CustomZone.active == True)
        )
        device_zone_range: dict[uuid.UUID, tuple[float, float]] = {
            row[0]: (float(row[1]), float(row[2]))
            for row in zone_range_result.all()
        }

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

    from app.config import settings as _settings
    semaphore = asyncio.Semaphore(max(1, _settings.max_concurrent_polls))

    async def _poll_with_sem(device_id, brise_id, is_critical, zone_min, zone_max):
        async with semaphore:
            return await poll_device(device_id, brise_id, is_critical,
                                     zone_ideal_min=zone_min, zone_ideal_max=zone_max)

    tasks = []
    for device, sector_name in rows:
        zone_range = device_zone_range.get(device.id)
        tasks.append(_poll_with_sem(
            device.id,
            device.brise_device_id,
            device.is_critical_environment,
            zone_range[0] if zone_range else None,
            zone_range[1] if zone_range else None,
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
