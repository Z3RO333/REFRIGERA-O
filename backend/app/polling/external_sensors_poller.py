"""
Poller para sensores externos com API HTTP/JSON (ex: Pró-Digital Term-1SW).

Dispositivos cadastrados com source_url preenchido são consultados diretamente
via GET {source_url}/telemetry e armazenados no mesmo pipeline de leituras.
Não recebem comandos — apenas monitoramento.
"""
import logging
import uuid
from datetime import datetime

import httpx
from sqlalchemy import select

from app.cache.device_cache import check_alert_cooldown, set_alert_cooldown
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.rules.alert_generator import generate_alert_if_needed
from app.rules.classifier import classify_status

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10  # segundos


async def poll_external_sensors() -> None:
    """Consulta todos os sensores externos ativos e armazena leituras."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Device)
            .where(Device.active == True, Device.source_url.is_not(None))
        )
        devices = result.scalars().all()

    if not devices:
        return

    logger.info("Polling %d sensor(es) externo(s)", len(devices))
    for device in devices:
        try:
            await _poll_one(device)
        except Exception as exc:
            logger.warning("Falha ao ler sensor %s: %s", device.name, exc)


async def _poll_one(device: Device) -> None:
    url = device.source_url.rstrip("/") + "/telemetry"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Sensor %s (%s) inacessível: %s", device.name, url, exc)
        await _write_no_reading(device)
        return

    temperature = _safe_float(data.get("temperature"))
    humidity    = _safe_float(data.get("humidity"))

    if temperature is None:
        logger.warning("Sensor %s retornou temperatura nula: %s", device.name, data)
        await _write_no_reading(device)
        return

    async with AsyncSessionLocal() as session:
        params_result = await session.execute(
            select(DeviceParameters).where(DeviceParameters.device_id == device.id)
        )
        params = params_result.scalar_one_or_none()
        setpoint_cool = params.setpoint_cool if params else 24

        status_row = await session.get(DeviceStatusLatest, device.id)
        consecutive_count = (status_row.consecutive_readings_count or 0) if status_row else 0
        current_status    = status_row.status_classification if status_row else None

        # Sensores externos não têm estado ligado/desligado — tratamos como sempre ligados
        status, delta, efficiency = classify_status(
            state=True,
            temperature=temperature,
            setpoint_cool=setpoint_cool,
            mode_ac=0,
            btu=device.btu or 12000,
            consumption_estimated=None,
            last_reading_time=datetime.utcnow(),  # acabou de responder = leitura válida
            consecutive_count=consecutive_count,
            current_status=current_status,
        )

        if status == current_status:
            consecutive_count += 1
        else:
            consecutive_count = 1

        now = datetime.utcnow()

        reading = DeviceReading(
            time=now,
            device_id=device.id,
            state=True,
            temperature=temperature,
            humidity=humidity,
            status_classification=status,
            delta_temp=delta,
            efficiency_score=efficiency,
        )
        session.add(reading)

        if status_row:
            status_row.state                     = True
            status_row.temperature               = temperature
            status_row.humidity                  = humidity
            status_row.status_classification     = status
            status_row.delta_temp                = delta
            status_row.efficiency_score          = efficiency
            status_row.consecutive_readings_count = consecutive_count
            status_row.updated_at                = now
        else:
            session.add(DeviceStatusLatest(
                device_id=device.id,
                state=True,
                temperature=temperature,
                humidity=humidity,
                status_classification=status,
                delta_temp=delta,
                efficiency_score=efficiency,
                consecutive_readings_count=consecutive_count,
                updated_at=now,
            ))

        alert_data = generate_alert_if_needed(
            device_id=device.id,
            status=status,
            delta_temp=delta,
            temperature=temperature,
            setpoint_cool=setpoint_cool,
            is_critical_environment=device.is_critical_environment,
            last_reading_time=now,
        )
        if alert_data:
            in_cooldown = await check_alert_cooldown(device.id, alert_data["alert_type"])
            if not in_cooldown:
                session.add(Alert(**alert_data))
                await set_alert_cooldown(device.id, alert_data["alert_type"])

        await session.commit()

    logger.debug("Sensor %s: %.1f°C  %.0f%%UR  %s", device.name, temperature, humidity or 0, status)


async def _write_no_reading(device: Device) -> None:
    """Registra SEM_LEITURA quando o sensor não responde."""
    from app.rules.classifier import STATUS_NO_READING
    async with AsyncSessionLocal() as session:
        status_row = await session.get(DeviceStatusLatest, device.id)
        now = datetime.utcnow()
        if status_row:
            status_row.status_classification = STATUS_NO_READING
            status_row.updated_at = now
        else:
            session.add(DeviceStatusLatest(
                device_id=device.id,
                status_classification=STATUS_NO_READING,
                updated_at=now,
            ))
        session.add(DeviceReading(
            time=now,
            device_id=device.id,
            status_classification=STATUS_NO_READING,
        ))
        await session.commit()


def _safe_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
