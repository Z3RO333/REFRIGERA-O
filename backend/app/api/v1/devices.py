import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.store import StoreSector, Store
from app.brise.client import brise_client
from app.schemas.device import DeviceControlCommand, DeviceParametersUpdate, DevicePositionUpdate
from app.cache.device_cache import get_device_status

router = APIRouter()

SETPOINT_COOL_MIN = 18
SETPOINT_COOL_MAX = 28
DEFAULT_PARAMETERS = {
    "mode_device": 1,
    "mode_ac": 0,
    "fan_speed": 2,
    "setpoint_cool": 24,
    "setpoint_heat": 20,
    "eco_cool": 22,
    "eco_heat": 18,
}

@router.get("")
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device, DeviceStatusLatest, StoreSector, Store)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(Device.active == True)
        .order_by(Device.name)
    )
    rows = result.all()
    return [_format_device(d, s, sec, st) for d, s, sec, st in rows]

@router.get("/search")
async def search_devices(q: str, limit: int = 10, db: AsyncSession = Depends(get_db)):
    term = q.strip()
    if not term:
        return []

    result = await db.execute(
        select(Device, DeviceStatusLatest, StoreSector, Store)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(
            Device.active == True,
            or_(
                Device.brise_device_id.ilike(f"%{term}%"),
                Device.name.ilike(f"%{term}%"),
            ),
        )
        .order_by(Device.brise_device_id, Device.name)
        .limit(limit)
    )
    rows = result.all()
    return [_format_device(d, s, sec, st) for d, s, sec, st in rows]

@router.get("/{device_id}")
async def get_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device, DeviceStatusLatest, DeviceParameters, StoreSector, Store)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .outerjoin(DeviceParameters, Device.id == DeviceParameters.device_id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(Device.id == device_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(404, "Dispositivo não encontrado")
    device, status, params, sector, store = row
    data = _format_device(device, status, sector, store)
    if params:
        data["parameters"] = {
            "mode_device": params.mode_device,
            "mode_ac": params.mode_ac,
            "fan_speed": params.fan_speed,
            "setpoint_cool": params.setpoint_cool,
            "setpoint_heat": params.setpoint_heat,
            "eco_cool": params.eco_cool,
            "eco_heat": params.eco_heat,
        }
    else:
        data["parameters"] = await _get_current_parameters(device_id, device.brise_device_id, db)
    return data

@router.get("/{device_id}/status")
async def get_device_status_cached(device_id: uuid.UUID):
    cached = await get_device_status(device_id)
    if cached:
        return cached
    return {"device_id": str(device_id), "status": "SEM_LEITURA"}

@router.put("/{device_id}/parameters")
async def update_device_parameters(
    device_id: uuid.UUID,
    params: DeviceParametersUpdate,
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    brise_params = {
        "modeDevice": params.mode_device,
        "modeAC": params.mode_ac,
        "fanSpeed": params.fan_speed,
        "setpointCool": params.setpoint_cool,
        "setpointHeat": params.setpoint_heat,
        "ecoCool": params.eco_cool,
        "ecoHeat": params.eco_heat,
    }
    success = await brise_client.put_parameters(device.brise_device_id, brise_params)
    if not success:
        raise HTTPException(503, "Falha ao comunicar com a Brise API")
    db_params = await _get_device_parameters_row(device_id, db)
    if db_params:
        db_params.mode_device = params.mode_device
        db_params.mode_ac = params.mode_ac
        db_params.fan_speed = params.fan_speed
        db_params.setpoint_cool = params.setpoint_cool
        db_params.setpoint_heat = params.setpoint_heat
        db_params.eco_cool = params.eco_cool
        db_params.eco_heat = params.eco_heat
        db_params.synced_at = datetime.utcnow()
    else:
        db_params = DeviceParameters(device_id=device_id, **params.model_dump())
        db.add(db_params)
    await db.commit()
    return {"message": "Parâmetros atualizados com sucesso"}

@router.post("/{device_id}/control")
async def control_device(
    device_id: uuid.UUID,
    command: DeviceControlCommand,
    db: AsyncSession = Depends(get_db),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")

    current_params = await _get_current_parameters(device_id, device.brise_device_id, db)
    next_params = current_params.copy()

    if command.action == "power_on":
        next_params["mode_device"] = 1
        next_params["mode_ac"] = 0
    elif command.action == "power_off":
        next_params["mode_device"] = 0
    elif command.action == "temperature_up":
        next_params["setpoint_cool"] = min(
            SETPOINT_COOL_MAX,
            next_params["setpoint_cool"] + command.step,
        )
    elif command.action == "temperature_down":
        next_params["setpoint_cool"] = max(
            SETPOINT_COOL_MIN,
            next_params["setpoint_cool"] - command.step,
        )

    brise_params = _to_brise_params(next_params)
    confirmed = await brise_client.put_parameters(device.brise_device_id, brise_params)

    await _persist_device_parameters(device_id, next_params, db)

    if command.action == "power_off":
        status = await db.get(DeviceStatusLatest, device_id)
        if status:
            status.state = False
            status.status_classification = "DESLIGADO"
            status.delta_temp = None
            status.updated_at = datetime.utcnow()

    await db.commit()
    return {
        "message": "Comando enviado",
        "confirmed": confirmed,
        "parameters": next_params,
    }

@router.put("/{device_id}/position")
async def update_device_position(device_id: uuid.UUID, pos: DevicePositionUpdate, db: AsyncSession = Depends(get_db)):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    device.position_x = pos.position_x
    device.position_y = pos.position_y
    await db.commit()
    return {"message": "Posição atualizada"}

@router.post("/{device_id}/sync")
async def force_sync(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.polling.device_poller import poll_device
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    import asyncio
    asyncio.create_task(poll_device(device_id, device.brise_device_id, device.is_critical_environment))
    return {"message": "Sincronização iniciada"}

@router.post("", status_code=201)
async def create_device(data: dict, db: AsyncSession = Depends(get_db)):
    device = Device(**data)
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return {"id": str(device.id)}

def _format_device(device, status, sector, store) -> dict:
    return {
        "id": str(device.id),
        "brise_id": device.brise_device_id,
        "name": device.name,
        "sector_id": str(device.sector_id) if device.sector_id else None,
        "sector_name": sector.name if sector else None,
        "store_id": str(sector.store_id) if sector else None,
        "store_name": store.name if store else None,
        "btu": device.btu,
        "position_x": device.position_x,
        "position_y": device.position_y,
        "is_critical_environment": device.is_critical_environment,
        "last_maintenance": device.last_maintenance.isoformat() if device.last_maintenance else None,
        "status": status.status_classification if status else "SEM_LEITURA",
        "temperature": status.temperature if status else None,
        "humidity": status.humidity if status else None,
        "delta_temp": status.delta_temp if status else None,
        "efficiency_score": status.efficiency_score if status else None,
        "state": status.state if status else None,
        "updated_at": status.updated_at.isoformat() if status else None,
    }

async def _get_current_parameters(device_id: uuid.UUID, brise_id: str, db: AsyncSession) -> dict:
    db_params = await _get_device_parameters_row(device_id, db)
    if db_params:
        return _db_params_to_dict(db_params)

    brise_params = await brise_client.get_parameters(brise_id)
    if brise_params:
        return {
            "mode_device": brise_params.modeDevice if brise_params.modeDevice is not None else DEFAULT_PARAMETERS["mode_device"],
            "mode_ac": brise_params.modeAC if brise_params.modeAC is not None else DEFAULT_PARAMETERS["mode_ac"],
            "fan_speed": brise_params.fanSpeed if brise_params.fanSpeed is not None else DEFAULT_PARAMETERS["fan_speed"],
            "setpoint_cool": brise_params.setpointCool if brise_params.setpointCool is not None else DEFAULT_PARAMETERS["setpoint_cool"],
            "setpoint_heat": brise_params.setpointHeat if brise_params.setpointHeat is not None else DEFAULT_PARAMETERS["setpoint_heat"],
            "eco_cool": brise_params.ecoCool if brise_params.ecoCool is not None else DEFAULT_PARAMETERS["eco_cool"],
            "eco_heat": brise_params.ecoHeat if brise_params.ecoHeat is not None else DEFAULT_PARAMETERS["eco_heat"],
        }

    return DEFAULT_PARAMETERS.copy()

def _db_params_to_dict(params: DeviceParameters) -> dict:
    return {
        "mode_device": params.mode_device,
        "mode_ac": params.mode_ac,
        "fan_speed": params.fan_speed,
        "setpoint_cool": params.setpoint_cool,
        "setpoint_heat": params.setpoint_heat,
        "eco_cool": params.eco_cool,
        "eco_heat": params.eco_heat,
    }

def _to_brise_params(params: dict) -> dict:
    return {
        "modeDevice": params["mode_device"],
        "modeAC": params["mode_ac"],
        "fanSpeed": params["fan_speed"],
        "setpointCool": params["setpoint_cool"],
        "setpointHeat": params["setpoint_heat"],
        "ecoCool": params["eco_cool"],
        "ecoHeat": params["eco_heat"],
    }

async def _persist_device_parameters(device_id: uuid.UUID, params: dict, db: AsyncSession):
    db_params = await _get_device_parameters_row(device_id, db)
    if db_params:
        db_params.mode_device = params["mode_device"]
        db_params.mode_ac = params["mode_ac"]
        db_params.fan_speed = params["fan_speed"]
        db_params.setpoint_cool = params["setpoint_cool"]
        db_params.setpoint_heat = params["setpoint_heat"]
        db_params.eco_cool = params["eco_cool"]
        db_params.eco_heat = params["eco_heat"]
        db_params.synced_at = datetime.utcnow()
        return

    db.add(DeviceParameters(device_id=device_id, **params, synced_at=datetime.utcnow()))

async def _get_device_parameters_row(device_id: uuid.UUID, db: AsyncSession) -> DeviceParameters | None:
    result = await db.execute(
        select(DeviceParameters).where(DeviceParameters.device_id == device_id)
    )
    return result.scalar_one_or_none()
