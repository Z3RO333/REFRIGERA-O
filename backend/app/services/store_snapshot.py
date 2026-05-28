"""
StoreSnapshot — retrato batched de uma loja para planeamento em lote.

Em vez de N queries por zona, carrega todos os dados da loja de uma vez.
O planeador avalia zonas a partir do snapshot, sem IR/VOLTA ao BD por zona.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_zone import CustomZone, CustomZoneDevice
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.store import StoreSector
from app.models.zone import ZoneAutomation


@dataclass
class DeviceSnap:
    device_id: uuid.UUID
    brise_device_id: str
    name: str
    sector_id: uuid.UUID | None
    position_x: float | None
    position_y: float | None
    btu: int
    source_url: str | None
    dnd: bool
    influence_radius_m: float
    # Status
    temperature: float | None
    status_classification: str
    state: bool | None
    updated_at: datetime | None
    efficiency_score: float | None
    delta_temp: float | None
    consumption_estimated: float | None
    # Parameters
    setpoint_cool: int | None
    setpoint_heat: int | None
    mode_device: int | None
    mode_ac: int | None
    fan_speed: int | None
    eco_cool: bool | None
    eco_heat: bool | None
    is_fresh: bool = False


@dataclass
class ZoneSnap:
    zone_key: str
    zone_id: uuid.UUID
    name: str
    ideal_min: float
    ideal_max: float
    zone_type: str
    # device_ids activos e sem conflito (conflict_overlap excluídos)
    device_ids: list[uuid.UUID] = field(default_factory=list)
    fresh_count: int = 0
    total_with_temp: int = 0

    @property
    def freshness_ratio(self) -> float:
        if self.total_with_temp == 0:
            return 0.0
        return round(self.fresh_count / self.total_with_temp, 3)


@dataclass
class AutomationSnap:
    zone_key: str
    store_id: uuid.UUID
    mode: str
    setpoint_min: int
    setpoint_max: int
    is_critical_zone: bool
    priority: str
    allowed_start_hour: int
    allowed_start_minute: int
    allowed_end_hour: int
    allowed_end_minute: int
    blocked_reason: str | None
    blocked_until: datetime | None


@dataclass
class StoreSnapshot:
    store_id: uuid.UUID
    taken_at: datetime
    epoch: int = 0
    devices: dict[uuid.UUID, DeviceSnap] = field(default_factory=dict)
    zones: dict[str, ZoneSnap] = field(default_factory=dict)
    automations: dict[str, AutomationSnap] = field(default_factory=dict)


async def build_store_snapshot(
    store_id: uuid.UUID,
    session: AsyncSession,
    stale_threshold_minutes: int = 15,
    store_epoch: int = 0,
) -> StoreSnapshot:
    """
    Carrega todos os dados de uma loja em 4 queries (em vez de N por zona).
    Exclui devices com binding_mode='conflict_overlap' das zonas.
    """
    now = datetime.utcnow()
    snap = StoreSnapshot(store_id=store_id, taken_at=now, epoch=store_epoch)
    stale_cutoff = now - timedelta(minutes=stale_threshold_minutes)

    # 1. Devices + status (join único por loja)
    dev_result = await session.execute(
        select(Device, DeviceStatusLatest)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .where(StoreSector.store_id == store_id, Device.active == True)
    )
    device_ids: list[uuid.UUID] = []
    for device, status in dev_result.all():
        is_fresh = bool(
            status is not None
            and status.updated_at is not None
            and status.updated_at >= stale_cutoff
            and status.temperature is not None
        )
        ds = DeviceSnap(
            device_id=device.id,
            brise_device_id=device.brise_device_id or "",
            name=device.name or "",
            sector_id=device.sector_id,
            position_x=float(device.position_x) if device.position_x is not None else None,
            position_y=float(device.position_y) if device.position_y is not None else None,
            btu=device.btu or 0,
            source_url=device.source_url,
            dnd=bool(device.dnd),
            influence_radius_m=float(device.influence_radius_m or 8),
            temperature=float(status.temperature) if status and status.temperature is not None else None,
            status_classification=status.status_classification if status else "SEM_LEITURA",
            state=status.state if status else None,
            updated_at=status.updated_at if status else None,
            efficiency_score=float(status.efficiency_score) if status and status.efficiency_score is not None else None,
            delta_temp=float(status.delta_temp) if status and status.delta_temp is not None else None,
            consumption_estimated=float(status.consumption_estimated) if status and status.consumption_estimated is not None else None,
            setpoint_cool=None, setpoint_heat=None,
            mode_device=None, mode_ac=None, fan_speed=None,
            eco_cool=None, eco_heat=None,
            is_fresh=is_fresh,
        )
        snap.devices[device.id] = ds
        device_ids.append(device.id)

    # 2. Parameters (batch por loja)
    if device_ids:
        params_result = await session.execute(
            select(DeviceParameters).where(DeviceParameters.device_id.in_(device_ids))
        )
        for p in params_result.scalars().all():
            ds = snap.devices.get(p.device_id)
            if ds:
                ds.setpoint_cool = p.setpoint_cool
                ds.setpoint_heat = p.setpoint_heat
                ds.mode_device = p.mode_device
                ds.mode_ac = p.mode_ac
                ds.fan_speed = p.fan_speed
                ds.eco_cool = p.eco_cool
                ds.eco_heat = p.eco_heat

    # 3. Zonas + bindings activos (excluindo conflict_overlap e inactive)
    zones_result = await session.execute(
        select(
            CustomZone.id, CustomZone.zone_key, CustomZone.name,
            CustomZone.ideal_min, CustomZone.ideal_max, CustomZone.zone_type,
            CustomZoneDevice.device_id, CustomZoneDevice.binding_mode,
        )
        .outerjoin(
            CustomZoneDevice,
            (CustomZone.id == CustomZoneDevice.zone_id)
            & (CustomZoneDevice.active == True)
            & (CustomZoneDevice.binding_mode != "conflict_overlap"),
        )
        .where(CustomZone.store_id == store_id, CustomZone.active == True)
    )
    for zone_id, zone_key, name, ideal_min, ideal_max, zone_type, dev_id, binding_mode in zones_result.all():
        if zone_key not in snap.zones:
            snap.zones[zone_key] = ZoneSnap(
                zone_key=zone_key, zone_id=zone_id, name=name,
                ideal_min=float(ideal_min), ideal_max=float(ideal_max),
                zone_type=zone_type,
            )
        if dev_id is not None:
            snap.zones[zone_key].device_ids.append(dev_id)
            ds = snap.devices.get(dev_id)
            if ds and ds.temperature is not None:
                snap.zones[zone_key].total_with_temp += 1
                if ds.is_fresh:
                    snap.zones[zone_key].fresh_count += 1

    # 4. Automações activas
    auto_result = await session.execute(
        select(ZoneAutomation).where(
            ZoneAutomation.store_id == store_id,
            ZoneAutomation.mode.not_in(["manual", "maintenance"]),
        )
    )
    for auto in auto_result.scalars().all():
        snap.automations[auto.zone_key] = AutomationSnap(
            zone_key=auto.zone_key,
            store_id=auto.store_id,
            mode=auto.mode,
            setpoint_min=auto.setpoint_min,
            setpoint_max=auto.setpoint_max,
            is_critical_zone=auto.is_critical_zone,
            priority=auto.priority or "conforto",
            allowed_start_hour=auto.allowed_start_hour,
            allowed_start_minute=auto.allowed_start_minute,
            allowed_end_hour=auto.allowed_end_hour,
            allowed_end_minute=auto.allowed_end_minute,
            blocked_reason=auto.blocked_reason,
            blocked_until=auto.blocked_until,
        )

    return snap


async def build_snapshots_for_all_stores(
    session: AsyncSession,
    epoch_map: dict[uuid.UUID, int] | None = None,
) -> dict[uuid.UUID, StoreSnapshot]:
    """Carrega snapshots de todas as lojas com automação activa (batch global)."""
    stores_result = await session.execute(
        select(ZoneAutomation.store_id).distinct().where(
            ZoneAutomation.mode.not_in(["manual", "maintenance"])
        )
    )
    store_ids = [row[0] for row in stores_result.all()]

    snapshots: dict[uuid.UUID, StoreSnapshot] = {}
    for sid in store_ids:
        epoch = (epoch_map or {}).get(sid, 0)
        snapshots[sid] = await build_store_snapshot(sid, session, store_epoch=epoch)

    return snapshots
