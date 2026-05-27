"""
Refresh imediato de status após comandos manuais (power_on/off, setpoint).

Diferente do poll_device (ciclo agendado a cada 5 min), este serviço:
  - É acionado logo após um comando confirmado pela Brise API
  - Usa lock separado para não interferir com o ciclo de polling
  - Atualiza DB + Redis e publica device.reading.new
  - Retorna o payload atualizado para o caller
"""
import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from app.brise.client import brise_client
from app.cache.device_cache import set_device_status, set_device_params
from app.cache.redis_client import redis_client
from app.db.session import AsyncSessionLocal
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.rules.classifier import classify_status

logger = logging.getLogger(__name__)

_REFRESH_LOCK_TTL = 25  # segundos — janela curta, só evita double-refresh simultâneo


async def refresh_device_status(
    device_id: uuid.UUID,
    brise_id: str,
) -> dict | None:
    """
    Busca o estado real do device na Brise API e persiste o resultado.

    Usa lock dedicado (refresh:lock:{id}) independente do polling lock,
    portanto não bloqueia nem é bloqueado pelo ciclo de poll_device.

    Retorna o payload de status atualizado, ou None se a Brise não respondeu.
    """
    lock_key = f"refresh:lock:{device_id}"
    lock_token = await redis_client.acquire_lock(lock_key, ttl=_REFRESH_LOCK_TTL)
    if not lock_token:
        logger.debug("refresh_device_status [%s]: lock já ativo, skip", brise_id)
        return None

    try:
        variables = await brise_client.get_variables(brise_id)
        if variables is None:
            logger.debug("refresh_device_status [%s]: Brise não retornou variáveis", brise_id)
            return None

        async with AsyncSessionLocal() as session:
            status_row = await session.get(DeviceStatusLatest, device_id)
            params_res = await session.execute(
                select(DeviceParameters).where(DeviceParameters.device_id == device_id)
            )
            params_row = params_res.scalar_one_or_none()

            remote_params = await brise_client.get_parameters(brise_id)
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

            device = await session.get(Device, device_id)
            if not device:
                return None
            btu = device.btu or 12000

            consecutive_count = (status_row.consecutive_readings_count or 0) if status_row else 0
            current_status = status_row.status_classification if status_row else None

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

            now = datetime.utcnow()
            if status_row:
                status_row.state = variables.state
                status_row.temperature = variables.temperature
                status_row.humidity = getattr(variables, "humidity", None)
                status_row.status_classification = status
                status_row.delta_temp = delta
                status_row.efficiency_score = efficiency
                status_row.updated_at = now
                if variables.temperature is not None:
                    status_row.last_success_at = now
                    status_row.consecutive_failures = 0
                    status_row.last_error = None

            cache_status = {
                "device_id": str(device_id),
                "brise_id": brise_id,
                "status": status,
                "temperature": variables.temperature,
                "humidity": getattr(variables, "humidity", None),
                "state": variables.state,
                "delta_temp": delta,
                "efficiency_score": efficiency,
                "setpoint_cool": setpoint_cool,
                "current_setpoint": setpoint_cool,
                "setpoint_synced_at": params_row.synced_at.isoformat() if params_row and params_row.synced_at else None,
                "setpoint_source": "brise_parameters_cache" if params_row else "default",
                "updated_at": now.isoformat(),
            }

            if params_row:
                cache_params = {
                    "mode_device": params_row.mode_device,
                    "mode_ac": params_row.mode_ac,
                    "fan_speed": params_row.fan_speed,
                    "setpoint_cool": params_row.setpoint_cool,
                    "setpoint_heat": params_row.setpoint_heat,
                    "eco_cool": params_row.eco_cool,
                    "eco_heat": params_row.eco_heat,
                    "synced_at": params_row.synced_at.isoformat() if params_row.synced_at else None,
                    "source": "brise_api" if remote_params else "db_cache",
                }
                await set_device_params(device_id, cache_params)

            # Registra leitura histórica para manter coerência com poll_device
            session.add(DeviceReading(
                time=now,
                device_id=device_id,
                state=variables.state,
                temperature=variables.temperature,
                humidity=getattr(variables, "humidity", None),
                consumption=getattr(variables, "consumption", None),
                consumption_estimated=variables.consumptionEstimated,
                status_classification=status,
                delta_temp=delta,
                efficiency_score=efficiency,
                raw_payload={"source": "command_refresh"},
            ))

            await session.commit()

        await set_device_status(device_id, cache_status)
        await redis_client.publish("device.reading.new", {
            **cache_status,
            "source": "command_refresh",
        })

        logger.info(
            "refresh_device_status [%s]: %s, temp=%s",
            brise_id, status, variables.temperature,
        )
        return cache_status

    finally:
        await redis_client.release_lock(lock_key, lock_token)


async def refresh_after_command(
    device_id: uuid.UUID,
    brise_id: str,
    initial_delay: float = 1.5,
    retries: int = 2,
) -> None:
    """
    Background task: tenta atualizar o status logo após um comando confirmado.

    Fluxo:
      1. Aguarda initial_delay (para a Brise processar o comando)
      2. Chama refresh_device_status
      3. Se Brise não respondeu, repete com back-off até `retries` vezes
    """
    for attempt in range(retries + 1):
        if attempt > 0:
            await asyncio.sleep(initial_delay * (attempt + 1))
        else:
            await asyncio.sleep(initial_delay)

        result = await refresh_device_status(device_id, brise_id)
        if result is not None:
            return

    logger.warning(
        "refresh_after_command [%s]: Brise não respondeu após %d tentativas",
        brise_id, retries + 1,
    )
