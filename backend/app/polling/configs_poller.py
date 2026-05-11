"""
Poll /configs de todos os devices ativos a cada poll_configs_interval segundos.
Sincroniza o campo `dnd` (Do Not Disturb) no modelo Device.
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.brise.client import brise_client
from app.db.session import AsyncSessionLocal
from app.models.device import Device

logger = logging.getLogger(__name__)


async def _sync_device_config(device_id, brise_id: str) -> None:
    try:
        config = await brise_client.get_configs(brise_id)
    except Exception as exc:
        logger.warning("Falha ao obter configs de %s: %s", brise_id, exc)
        return
    if config is None:
        return
    async with AsyncSessionLocal() as session:
        device = await session.get(Device, device_id)
        if not device:
            return
        changed = False
        if config.dnd is not None and device.dnd != config.dnd:
            device.dnd = config.dnd
            changed = True
        if config.enableFan is not None and device.enable_fan != config.enableFan:
            device.enable_fan = config.enableFan
            changed = True
        if config.enableHeat is not None and device.enable_heat != config.enableHeat:
            device.enable_heat = config.enableHeat
            changed = True
        # Sincroniza BTU — crítico para cálculo de BAIXA_EFICIÊNCIA
        if config.btu is not None and config.btu > 0 and device.btu != config.btu:
            logger.info("Device %s: btu %d → %d (Brise)", brise_id, device.btu, config.btu)
            device.btu = config.btu
            changed = True
        if changed:
            device.updated_at = datetime.utcnow()
            await session.commit()


async def poll_configs_for_all() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Device.id, Device.brise_device_id)
            .where(
                Device.active == True,
                Device.brise_device_id.not_like("MANUAL-%"),
                Device.source_url.is_(None),   # sensores externos não têm configs na Brise
            )
        )
        rows = result.all()

    logger.info("configs_poller: sincronizando %d devices", len(rows))
    tasks = [_sync_device_config(row.id, row.brise_device_id) for row in rows]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("configs_poller: concluído")
