import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.session import get_db
from app.models.device import Device
from app.models.reading import DeviceReading
from app.models.store import Store, StoreSector

router = APIRouter()


def _interval_hours() -> float:
    return settings.poll_variables_interval / 3600


def _estimated_kw(raw_consumption_estimated: float | None) -> float | None:
    if raw_consumption_estimated is None:
        return None
    return float(raw_consumption_estimated) * settings.energy_consumption_scale


def _energy_kwh(raw_consumption_estimated: float | None) -> float | None:
    estimated_kw = _estimated_kw(raw_consumption_estimated)
    if estimated_kw is None:
        return None
    return estimated_kw * _interval_hours()


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _effective_energy_price(energy_price: float | None) -> float:
    return settings.energy_price_per_kwh if energy_price is None else energy_price


def _estimated_cost(kwh: float | None, energy_price: float) -> float | None:
    if kwh is None:
        return None
    return round(kwh * energy_price, 2)


@router.get("/devices/{device_id}")
async def get_device_history(
    device_id: uuid.UUID,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(DeviceReading)
        .where(DeviceReading.device_id == device_id, DeviceReading.time >= since)
        .order_by(DeviceReading.time.asc())
    )
    readings = result.scalars().all()
    return {
        "device_id": str(device_id),
        "hours": hours,
        "readings": [
            {
                "time": r.time.isoformat(),
                "temperature": r.temperature,
                "humidity": r.humidity,
                "status_classification": r.status_classification,
                "delta_temp": r.delta_temp,
                "efficiency_score": r.efficiency_score,
                "state": r.state,
                "consumption": r.consumption,
                "consumption_estimated": r.consumption_estimated,
                "consumption_estimated_kw": _estimated_kw(r.consumption_estimated),
                "estimated_kwh": _energy_kwh(r.consumption_estimated),
            }
            for r in readings
        ],
    }

@router.get("/devices/{device_id}/stats")
async def get_device_stats(
    device_id: uuid.UUID,
    hours: int = Query(24, ge=1, le=720),
    energy_price: float | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(
            func.avg(DeviceReading.temperature).label("avg_temp"),
            func.max(DeviceReading.temperature).label("max_temp"),
            func.min(DeviceReading.temperature).label("min_temp"),
            func.avg(DeviceReading.efficiency_score).label("avg_efficiency"),
            func.count(DeviceReading.id).filter(DeviceReading.status_classification == "CRÍTICO").label("count_critical"),
            func.count(DeviceReading.id).filter(DeviceReading.status_classification == "ATENÇÃO").label("count_warning"),
            func.count(DeviceReading.id).filter(DeviceReading.status_classification == "NORMAL").label("count_normal"),
            func.avg(DeviceReading.consumption_estimated).label("avg_consumption_kw"),
            func.max(DeviceReading.consumption_estimated).label("peak_consumption_kw"),
            (func.sum(DeviceReading.consumption_estimated) * _interval_hours()).label("total_kwh"),
        )
        .where(DeviceReading.device_id == device_id, DeviceReading.time >= since)
    )
    row = result.first()
    interval_hours = _interval_hours()
    price = _effective_energy_price(energy_price)
    total_kwh = _round_or_none(
        float(row.total_kwh) * settings.energy_consumption_scale if row.total_kwh is not None else None
    )
    return {
        "avg_temp": float(row.avg_temp) if row.avg_temp else None,
        "max_temp": float(row.max_temp) if row.max_temp else None,
        "min_temp": float(row.min_temp) if row.min_temp else None,
        "avg_efficiency": float(row.avg_efficiency) if row.avg_efficiency else None,
        "hours_critical": float(row.count_critical or 0) * interval_hours,
        "hours_warning": float(row.count_warning or 0) * interval_hours,
        "hours_normal": float(row.count_normal or 0) * interval_hours,
        "avg_consumption_kw": _round_or_none(_estimated_kw(row.avg_consumption_kw)),
        "peak_consumption_kw": _round_or_none(_estimated_kw(row.peak_consumption_kw)),
        "total_kwh": total_kwh,
        "energy_price_per_kwh": price,
        "energy_consumption_scale": settings.energy_consumption_scale,
        "estimated_cost": _estimated_cost(total_kwh, price),
    }


@router.get("/devices/{device_id}/consumption")
async def get_device_consumption(
    device_id: uuid.UUID,
    hours: int = Query(24, ge=1, le=720),
    energy_price: float | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    price = _effective_energy_price(energy_price)
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(DeviceReading)
        .where(DeviceReading.device_id == device_id, DeviceReading.time >= since)
        .order_by(DeviceReading.time.asc())
    )
    readings = result.scalars().all()

    points = []
    total_kwh = 0.0
    valid_samples = 0
    estimated_values: list[float] = []

    for reading in readings:
        raw_estimated = reading.consumption_estimated
        estimated_kw = _estimated_kw(raw_estimated)
        estimated_kwh = _energy_kwh(raw_estimated)
        if estimated_kwh is not None:
            total_kwh += estimated_kwh
            valid_samples += 1
        if estimated_kw is not None:
            estimated_values.append(float(estimated_kw))

        points.append({
            "time": reading.time.isoformat(),
            "state": reading.state,
            "status_classification": reading.status_classification,
            "consumption": reading.consumption,
            "raw_consumption_estimated": raw_estimated,
            "consumption_estimated_kw": estimated_kw,
            "estimated_kwh": estimated_kwh,
        })

    return {
        "device_id": str(device_id),
        "hours": hours,
        "sample_interval_hours": _interval_hours(),
        "summary": {
            "samples": len(readings),
            "valid_consumption_samples": valid_samples,
            "avg_consumption_kw": round(sum(estimated_values) / len(estimated_values), 2) if estimated_values else None,
            "peak_consumption_kw": round(max(estimated_values), 2) if estimated_values else None,
            "total_estimated_kwh": round(total_kwh, 2),
            "energy_price_per_kwh": price,
            "energy_consumption_scale": settings.energy_consumption_scale,
            "estimated_cost": _estimated_cost(total_kwh, price),
        },
        "readings": points,
    }


@router.get("/consumption/summary")
async def get_consumption_summary(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(10, ge=1, le=100),
    store_id: uuid.UUID | None = Query(None),
    energy_price: float | None = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    price = _effective_energy_price(energy_price)
    since = datetime.utcnow() - timedelta(hours=hours)
    interval_hours = _interval_hours()
    filters = [
        Device.active == True,
        DeviceReading.time >= since,
        DeviceReading.consumption_estimated.is_not(None),
    ]
    if store_id:
        filters.append(StoreSector.store_id == store_id)

    total_result = await db.execute(
        select(
            func.count(DeviceReading.id).label("samples"),
            func.sum(DeviceReading.consumption_estimated).label("sum_kw"),
            func.avg(DeviceReading.consumption_estimated).label("avg_kw"),
            func.max(DeviceReading.consumption_estimated).label("peak_kw"),
        )
        .join(Device, DeviceReading.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .where(*filters)
    )
    total_row = total_result.first()
    total_kwh = (
        float(total_row.sum_kw or 0) * settings.energy_consumption_scale * interval_hours
        if total_row else 0.0
    )

    sum_kw = func.sum(DeviceReading.consumption_estimated)
    by_device_result = await db.execute(
        select(
            Device.id.label("device_id"),
            Device.brise_device_id,
            Device.name.label("device_name"),
            Store.name.label("store_name"),
            StoreSector.name.label("sector_name"),
            func.count(DeviceReading.id).label("samples"),
            func.avg(DeviceReading.consumption_estimated).label("avg_kw"),
            func.max(DeviceReading.consumption_estimated).label("peak_kw"),
            sum_kw.label("sum_kw"),
        )
        .join(Device, DeviceReading.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(*filters)
        .group_by(Device.id, Device.brise_device_id, Device.name, Store.name, StoreSector.name)
        .order_by(sum_kw.desc())
        .limit(limit)
    )

    store_sum_kw = func.sum(DeviceReading.consumption_estimated)
    by_store_result = await db.execute(
        select(
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.count(DeviceReading.id).label("samples"),
            func.count(func.distinct(Device.id)).label("devices"),
            func.avg(DeviceReading.consumption_estimated).label("avg_kw"),
            func.max(DeviceReading.consumption_estimated).label("peak_kw"),
            store_sum_kw.label("sum_kw"),
        )
        .join(Device, DeviceReading.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(*filters)
        .group_by(Store.id, Store.name)
        .order_by(store_sum_kw.desc())
    )

    sector_sum_kw = func.sum(DeviceReading.consumption_estimated)
    by_sector_result = await db.execute(
        select(
            StoreSector.id.label("sector_id"),
            StoreSector.name.label("sector_name"),
            Store.name.label("store_name"),
            func.count(DeviceReading.id).label("samples"),
            func.count(func.distinct(Device.id)).label("devices"),
            func.avg(DeviceReading.consumption_estimated).label("avg_kw"),
            func.max(DeviceReading.consumption_estimated).label("peak_kw"),
            sector_sum_kw.label("sum_kw"),
        )
        .join(Device, DeviceReading.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(*filters)
        .group_by(StoreSector.id, StoreSector.name, Store.name)
        .order_by(sector_sum_kw.desc())
        .limit(limit)
    )

    def item_kwh(row) -> float:
        return float(row.sum_kw or 0) * settings.energy_consumption_scale * interval_hours

    def cost(kwh: float) -> float | None:
        return _estimated_cost(kwh, price)

    by_device = []
    for row in by_device_result.all():
        kwh = item_kwh(row)
        by_device.append({
            "device_id": str(row.device_id),
            "brise_id": row.brise_device_id,
            "device_name": row.device_name,
            "store_name": row.store_name,
            "sector_name": row.sector_name,
            "samples": row.samples,
            "avg_consumption_kw": _round_or_none(_estimated_kw(row.avg_kw)),
            "peak_consumption_kw": _round_or_none(_estimated_kw(row.peak_kw)),
            "total_estimated_kwh": round(kwh, 2),
            "estimated_cost": cost(kwh),
        })

    by_store = []
    for row in by_store_result.all():
        kwh = item_kwh(row)
        by_store.append({
            "store_id": str(row.store_id) if row.store_id else None,
            "store_name": row.store_name,
            "devices": row.devices,
            "samples": row.samples,
            "avg_consumption_kw": _round_or_none(_estimated_kw(row.avg_kw)),
            "peak_consumption_kw": _round_or_none(_estimated_kw(row.peak_kw)),
            "total_estimated_kwh": round(kwh, 2),
            "estimated_cost": cost(kwh),
        })

    by_sector = []
    for row in by_sector_result.all():
        kwh = item_kwh(row)
        by_sector.append({
            "sector_id": str(row.sector_id) if row.sector_id else None,
            "sector_name": row.sector_name,
            "store_name": row.store_name,
            "devices": row.devices,
            "samples": row.samples,
            "avg_consumption_kw": _round_or_none(_estimated_kw(row.avg_kw)),
            "peak_consumption_kw": _round_or_none(_estimated_kw(row.peak_kw)),
            "total_estimated_kwh": round(kwh, 2),
            "estimated_cost": cost(kwh),
        })

    return {
        "hours": hours,
        "store_id": str(store_id) if store_id else None,
        "sample_interval_hours": interval_hours,
        "summary": {
            "samples": total_row.samples if total_row else 0,
            "avg_consumption_kw": _round_or_none(_estimated_kw(total_row.avg_kw if total_row else None)),
            "peak_consumption_kw": _round_or_none(_estimated_kw(total_row.peak_kw if total_row else None)),
            "total_estimated_kwh": round(total_kwh, 2),
            "energy_price_per_kwh": price,
            "energy_consumption_scale": settings.energy_consumption_scale,
            "estimated_cost": cost(total_kwh),
        },
        "by_store": by_store,
        "by_sector": by_sector,
        "top_devices": by_device,
    }
