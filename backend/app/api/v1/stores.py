import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.session import get_db
from app.models.store import Store, StoreSector
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.user import User
from app.api.v1.auth import require_role
from app.schemas.store import FloorPlanUpdate, SectorCreate, StoreCreate

router = APIRouter()

SETPOINT_STALE_MINUTES = 30
SETPOINT_COOL_MIN = 18
SETPOINT_COOL_MAX = 28


def _setpoint_fields(params: DeviceParameters | None) -> dict:
    synced_at = params.synced_at if params and params.synced_at else None
    current_setpoint = params.setpoint_cool if params else None
    stale = synced_at is None or synced_at < datetime.utcnow() - timedelta(minutes=SETPOINT_STALE_MINUTES)
    return {
        "setpoint_cool": current_setpoint,
        "current_setpoint": current_setpoint,
        "setpoint_synced_at": synced_at.isoformat() if synced_at else None,
        "setpoint_stale": stale,
        "setpoint_source": "brise_parameters_cache" if params else "unavailable",
        "min_allowed_setpoint": SETPOINT_COOL_MIN,
        "max_allowed_setpoint": SETPOINT_COOL_MAX,
    }

@router.get("")
async def list_stores(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Store,
            func.count(Device.id).label("device_count"),
            func.max(DeviceStatusLatest.updated_at).label("last_reading_at"),
        )
        .outerjoin(StoreSector, Store.id == StoreSector.store_id)
        .outerjoin(Device, (StoreSector.id == Device.sector_id) & (Device.active == True))
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .where(Store.active == True)
        .group_by(Store.id)
        .order_by(Store.name)
    )
    stores = []
    for store, device_count, last_reading_at in result.all():
        code_name = f"{store.code} {store.name}".upper()
        if "ESCRIT" in code_name:
            kind = "ESCRITORIO"
        elif store.code == "MATRIZ" or "MATRIZ" in code_name:
            kind = "MATRIZ"
        elif "FARMA" in code_name:
            kind = "FARMA"
        elif "CD" in code_name or "CENTRO" in code_name:
            kind = "CD"
        else:
            kind = "LOJA"
        stores.append({
            "id": str(store.id),
            "name": store.name,
            "code": store.code,
            "city": store.city,
            "kind": kind,
            "device_count": device_count or 0,
            "last_reading_at": last_reading_at.isoformat() if last_reading_at else None,
        })
    return stores

@router.post("", status_code=201)
async def create_store(data: StoreCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_role("ADMIN"))):
    store = Store(**data.model_dump())
    db.add(store)
    await db.commit()
    await db.refresh(store)
    return {"id": str(store.id), "name": store.name}

@router.get("/{store_id}/devices")
async def get_store_devices(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device, DeviceStatusLatest, StoreSector, DeviceParameters)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .outerjoin(DeviceParameters, Device.id == DeviceParameters.device_id)
        .where(StoreSector.store_id == store_id, Device.active == True)
    )
    rows = result.all()
    devices = []
    for device, status, sector, params in rows:
        devices.append({
            "id": str(device.id),
            "brise_id": device.brise_device_id,
            "name": device.name,
            "sector_id": str(device.sector_id) if device.sector_id else None,
            "sector_name": sector.name if sector else None,
            "btu": device.btu,
            "position_x": device.position_x,
            "position_y": device.position_y,
            "is_critical_environment": device.is_critical_environment,
            "is_external_sensor": device.source_url is not None,
            "influence_radius_m": device.influence_radius_m if hasattr(device, "influence_radius_m") else 8,
            "source_url": device.source_url,
            "status": status.status_classification if status else "SEM_LEITURA",
            "temperature": status.temperature if status else None,
            "humidity": status.humidity if status else None,
            "consumption": status.consumption if status else None,
            "consumption_estimated": status.consumption_estimated if status else None,
            "consumption_estimated_kw": (
                status.consumption_estimated * settings.energy_consumption_scale
                if status and status.consumption_estimated is not None else None
            ),
            "delta_temp": status.delta_temp if status else None,
            "efficiency_score": status.efficiency_score if status else None,
            "state": status.state if status else None,
            **_setpoint_fields(params),
            "updated_at": status.updated_at.isoformat() if status else None,
        })
    return {"devices": devices}

@router.get("/{store_id}/sectors")
async def get_store_sectors(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StoreSector).where(StoreSector.store_id == store_id).order_by(StoreSector.name)
    )
    sectors = result.scalars().all()
    return [{"id": str(s.id), "name": s.name, "floor": s.floor, "floor_plan_url": s.floor_plan_url, "is_critical": s.is_critical} for s in sectors]

@router.post("/{store_id}/sectors", status_code=201)
async def create_sector(store_id: uuid.UUID, data: SectorCreate, db: AsyncSession = Depends(get_db), _: User = Depends(require_role("ADMIN"))):
    sector = StoreSector(store_id=store_id, **data.model_dump())
    db.add(sector)
    await db.commit()
    await db.refresh(sector)
    return {"id": str(sector.id), "name": sector.name}

@router.put("/{store_id}/sectors/{sector_id}/floor-plan")
async def update_floor_plan(store_id: uuid.UUID, sector_id: uuid.UUID, data: FloorPlanUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_role("ADMIN"))):
    sector = await db.get(StoreSector, sector_id)
    if not sector or sector.store_id != store_id:
        raise HTTPException(404, "Setor não encontrado")
    sector.floor_plan_url = data.floor_plan_url
    await db.commit()
    return {"message": "Planta atualizada"}
