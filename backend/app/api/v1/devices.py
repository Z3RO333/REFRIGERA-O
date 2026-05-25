import asyncio
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.store import StoreSector, Store
from app.brise.client import brise_client
from app.schemas.device import (
    DeviceControlCommand, DeviceCreate, DeviceMetadataUpdate, DeviceParametersUpdate,
    DevicePositionUpdate, ExternalSensorCreate,
)
from app.cache.device_cache import get_device_status, set_device_params
from app.cache.redis_client import redis_client
from app.security.network import validate_sensor_url
from app.models.user import User
from app.api.v1.auth import get_current_user, require_role
from app.services.audit_service import log_action
from app.services.zone_controller import KILL_SWITCH_KEY
from app.services.device_refresh import refresh_after_command
from app.config import settings

router = APIRouter()

SETPOINT_COOL_MIN = 18
SETPOINT_COOL_MAX = 28
SETPOINT_STALE_MINUTES = 30
DEFAULT_PARAMETERS = {
    "mode_device": 1,
    "mode_ac": 0,
    "fan_speed": 2,
    "setpoint_cool": 24,
    "setpoint_heat": 20,
    "eco_cool": 22,
    "eco_heat": 18,
}


def _validate_control_action(
    device: Device,
    status: DeviceStatusLatest | None,
    current_params: dict,
    next_params: dict,
    command: DeviceControlCommand,
) -> tuple[str, str] | None:
    if device.source_url is not None:
        return "INVALID_TARGET_SENSOR", "Sensor externo não recebe comandos"
    if device.dnd:
        return "DEVICE_BLOCKED", "Dispositivo em modo DND — comando bloqueado pelo equipamento"
    if not device.active:
        return "DEVICE_BLOCKED", "Dispositivo inativo — comando bloqueado"

    communication_bad = status is None
    if status:
        if status.status_classification == "SEM_LEITURA":
            communication_bad = True
        elif status.updated_at and status.updated_at < datetime.utcnow() - timedelta(minutes=settings.offline_threshold_minutes):
            communication_bad = True
    if communication_bad:
        return "DEVICE_WITHOUT_COMMUNICATION", "Dispositivo sem comunicação/leitura confiável — valide telemetria antes de comandar"

    if command.action == "power_on":
        already_on = status.state is True if status and status.state is not None else current_params.get("mode_device") == 1
        if already_on:
            return "NO_OP_ALREADY_ON", "Equipamento já está ligado"
    elif command.action == "power_off":
        already_off = status.state is False if status and status.state is not None else current_params.get("mode_device") == 0
        if already_off:
            return "NO_OP_ALREADY_OFF", "Equipamento já está desligado"
    elif command.action in {"temperature_up", "temperature_down", "set_temperature"}:
        temperature = next_params.get("setpoint_cool")
        if temperature is None or temperature < SETPOINT_COOL_MIN or temperature > SETPOINT_COOL_MAX:
            return "INVALID_TEMPERATURE_RANGE", "Temperatura fora da faixa permitida (18-28°C)"
        if next_params.get("setpoint_cool") == current_params.get("setpoint_cool"):
            return "NO_OP_SETPOINT_EQUALS_CURRENT", "Setpoint solicitado é igual ao setpoint atual ou já está no limite operacional"

    return None


def _params_synced_at(params: DeviceParameters | None) -> datetime | None:
    return params.synced_at if params and params.synced_at else None


def _params_are_stale(params: DeviceParameters | None) -> bool:
    synced_at = _params_synced_at(params)
    if synced_at is None:
        return True
    return synced_at < datetime.utcnow() - timedelta(minutes=SETPOINT_STALE_MINUTES)


def _brise_params_to_dict(brise_params) -> dict:
    return {
        "mode_device": brise_params.modeDevice if brise_params.modeDevice is not None else DEFAULT_PARAMETERS["mode_device"],
        "mode_ac": brise_params.modeAC if brise_params.modeAC is not None else DEFAULT_PARAMETERS["mode_ac"],
        "fan_speed": brise_params.fanSpeed if brise_params.fanSpeed is not None else DEFAULT_PARAMETERS["fan_speed"],
        "setpoint_cool": brise_params.setpointCool if brise_params.setpointCool is not None else DEFAULT_PARAMETERS["setpoint_cool"],
        "setpoint_heat": brise_params.setpointHeat if brise_params.setpointHeat is not None else DEFAULT_PARAMETERS["setpoint_heat"],
        "eco_cool": brise_params.ecoCool if brise_params.ecoCool is not None else DEFAULT_PARAMETERS["eco_cool"],
        "eco_heat": brise_params.ecoHeat if brise_params.ecoHeat is not None else DEFAULT_PARAMETERS["eco_heat"],
    }


def _enrich_parameter_fields(data: dict, params: DeviceParameters | None) -> dict:
    synced_at = _params_synced_at(params)
    setpoint = params.setpoint_cool if params else None
    data.update({
        "setpoint_cool": setpoint,
        "current_setpoint": setpoint,
        "setpoint_synced_at": synced_at.isoformat() if synced_at else None,
        "setpoint_stale": _params_are_stale(params),
        "setpoint_source": "brise_parameters_cache" if params else "unavailable",
        "min_allowed_setpoint": SETPOINT_COOL_MIN,
        "max_allowed_setpoint": SETPOINT_COOL_MAX,
    })
    return data

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
    current_params = await _get_current_parameters(device_id, device.brise_device_id, db)
    await db.commit()
    params = await _get_device_parameters_row(device_id, db)
    data["parameters"] = current_params
    _enrich_parameter_fields(data, params)
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
    _: User = Depends(require_role("EDITOR", "ADMIN")),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    if device.dnd:
        raise HTTPException(409, "Dispositivo em modo DND — ajuste manual bloqueado pelo equipamento")
    if device.source_url is not None:
        raise HTTPException(409, "Sensor externo não recebe comandos Brise")
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
    await set_device_params(device_id, {
        "mode_device": params.mode_device,
        "mode_ac": params.mode_ac,
        "fan_speed": params.fan_speed,
        "setpoint_cool": params.setpoint_cool,
        "setpoint_heat": params.setpoint_heat,
        "eco_cool": params.eco_cool,
        "eco_heat": params.eco_heat,
        "synced_at": datetime.utcnow().isoformat(),
    })
    return {"message": "Parâmetros atualizados com sucesso"}

@router.post("/{device_id}/control")
async def control_device(
    device_id: uuid.UUID,
    command: DeviceControlCommand,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")

    # Bug 4: respeitar kill switch global — bloqueia automação E comandos manuais
    if await redis_client.exists(KILL_SWITCH_KEY):
        raise HTTPException(409, "Kill switch global ativo — todos os comandos estão bloqueados. Reative a automação antes de enviar comandos.")

    # Resolve store/sector para enriquecer o audit_log
    sector_store = await db.execute(
        select(StoreSector, Store)
        .join(Store, StoreSector.store_id == Store.id)
        .where(StoreSector.id == device.sector_id)
    )
    sector_row = sector_store.first()
    _sector = sector_row[0] if sector_row else None
    _store  = sector_row[1] if sector_row else None

    status = await db.get(DeviceStatusLatest, device_id)
    should_pre_validate = (
        device.source_url is not None
        or device.dnd
        or not device.active
        or status is None
        or bool(status and (
            status.status_classification == "SEM_LEITURA"
            or (
                status.updated_at
                and status.updated_at < datetime.utcnow() - timedelta(minutes=settings.offline_threshold_minutes)
            )
        ))
    )
    pre_validation = (
        _validate_control_action(device, status, DEFAULT_PARAMETERS.copy(), DEFAULT_PARAMETERS.copy(), command)
        if should_pre_validate else None
    )
    if pre_validation:
        validation_code, validation_message = pre_validation
        action_labels = {
            "power_on": "ligar",
            "power_off": "desligar",
            "temperature_up": "aumentar setpoint",
            "temperature_down": "reduzir setpoint",
        }
        label = action_labels.get(command.action, command.action)
        await log_action(
            db, "device_control",
            f"{current_user.name} tentou {label} — {device.name}, mas o comando foi bloqueado: {validation_message}"
            + (f" [{_sector.name}]" if _sector else ""),
            user=current_user,
            device_id=device_id,
            device_name=device.name,
            store_id=_store.id if _store else None,
            store_name=_store.name if _store else None,
            sector_name=_sector.name if _sector else None,
            extra_data={"action": command.action, "step": command.step, "confirmed": False, "rejected": validation_code},
            severity="LOW" if validation_code.startswith("NO_OP") else "MEDIUM",
        )
        await db.commit()
        raise HTTPException(409, validation_message)

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

    is_temp_action = "temperature" in command.action
    is_power_action = command.action in {"power_on", "power_off"}
    old_sp = current_params.get("setpoint_cool")
    new_sp = next_params.get("setpoint_cool")
    old_power = current_params.get("mode_device")
    new_power = next_params.get("mode_device")
    action_labels = {
        "power_on":         "ligou",
        "power_off":        "desligou",
        "temperature_up":   f"↑ setpoint {old_sp}°C → {new_sp}°C",
        "temperature_down": f"↓ setpoint {old_sp}°C → {new_sp}°C",
    }
    label = action_labels.get(command.action, command.action)

    validation_error = _validate_control_action(device, status, current_params, next_params, command)
    if validation_error:
        validation_code, validation_message = validation_error
        await log_action(
            db, "device_control",
            f"{current_user.name} tentou {label} — {device.name}, mas o comando foi bloqueado: {validation_message}"
            + (f" [{_sector.name}]" if _sector else ""),
            user=current_user,
            device_id=device_id,
            device_name=device.name,
            store_id=_store.id if _store else None,
            store_name=_store.name if _store else None,
            sector_name=_sector.name if _sector else None,
            old_value=str(old_sp) if is_temp_action else (str(old_power) if is_power_action else None),
            new_value=str(new_sp) if is_temp_action else (str(new_power) if is_power_action else None),
            extra_data={"action": command.action, "step": command.step, "confirmed": False, "rejected": validation_code},
            severity="LOW" if validation_code.startswith("NO_OP") else "MEDIUM",
        )
        await db.commit()
        raise HTTPException(409, validation_message)

    brise_params = _to_brise_params(next_params)
    confirmed = await brise_client.put_parameters(device.brise_device_id, brise_params)

    if not confirmed:
        await log_action(
            db, "device_control",
            f"{current_user.name} tentou {label} — {device.name}, mas a Brise API recusou/falhou"
            + (f" [{_sector.name}]" if _sector else ""),
            user=current_user,
            device_id=device_id,
            device_name=device.name,
            store_id=_store.id if _store else None,
            store_name=_store.name if _store else None,
            sector_name=_sector.name if _sector else None,
            old_value=str(old_sp) if is_temp_action else (str(old_power) if is_power_action else None),
            new_value=str(new_sp) if is_temp_action else (str(new_power) if is_power_action else None),
            extra_data={"action": command.action, "step": command.step, "confirmed": False},
            severity="HIGH",
        )
        await db.commit()
        await redis_client.publish("device.command.failed", {
            "device_id": str(device_id),
            "device_name": device.name,
            "action": command.action,
            "confirmed": False,
            "by": current_user.name,
        })
        raise HTTPException(503, "Falha ao comunicar com a Brise API")

    await _persist_device_parameters(device_id, next_params, db)

    if command.action in {"power_on", "power_off"}:
        if status:
            status.state = command.action == "power_on"
            if command.action == "power_off":
                status.status_classification = "DESLIGADO"
                status.delta_temp = None
            elif status.status_classification == "DESLIGADO":
                status.status_classification = "AGUARDANDO_LEITURA"
            status.updated_at = datetime.utcnow()

    await log_action(
        db, "device_control",
        f"{current_user.name} {label} — {device.name}" + (f" [{_sector.name}]" if _sector else ""),
        user=current_user,
        device_id=device_id,
        device_name=device.name,
        store_id=_store.id if _store else None,
        store_name=_store.name if _store else None,
        sector_name=_sector.name if _sector else None,
        old_value=str(old_sp) if is_temp_action else (str(old_power) if is_power_action else None),
        new_value=str(new_sp) if is_temp_action else (str(new_power) if is_power_action else None),
        extra_data={"action": command.action, "step": command.step, "confirmed": True},
    )
    await db.commit()

    # Atualiza cache Redis de parâmetros imediatamente após commit
    await set_device_params(device_id, {**next_params, "synced_at": datetime.utcnow().isoformat()})

    await redis_client.publish("device.command.sent", {
        "device_id": str(device_id),
        "device_name": device.name,
        "action": command.action,
        "confirmed": True,
        "by": current_user.name,
    })

    # Dispara refresh em background para atualizar status real após o comando
    asyncio.create_task(refresh_after_command(device_id, device.brise_device_id))

    return {
        "message": "Comando enviado",
        "confirmed": True,
        "parameters": next_params,
    }

@router.post("/{device_id}/refresh-status")
async def refresh_device_status_endpoint(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("EDITOR", "ADMIN")),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    if device.source_url is not None:
        raise HTTPException(409, "Sensor externo não suporta refresh manual")

    from app.services.device_refresh import refresh_device_status
    result = await refresh_device_status(device_id, device.brise_device_id)
    if result is None:
        raise HTTPException(503, "Brise API não retornou dados — tente novamente em instantes")
    return result


@router.put("/{device_id}/position")
async def update_device_position(
    device_id: uuid.UUID,
    pos: DevicePositionUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    device.position_x = pos.position_x
    device.position_y = pos.position_y
    await db.commit()
    return {"message": "Posição atualizada"}

@router.patch("/{device_id}")
async def update_device_metadata(
    device_id: uuid.UUID,
    data: DeviceMetadataUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    device.btu = data.btu
    device.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "message": "Dispositivo atualizado",
        "device_id": str(device.id),
        "btu": device.btu,
    }

@router.get("/{device_id}/brise-schedules")
async def get_brise_schedules(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    if device.source_url is not None:
        return []
    schedules = await brise_client.get_schedules(device.brise_device_id)
    return [_format_schedule(s) for s in schedules]


def _format_schedule(s) -> dict:
    from datetime import timezone
    days_map = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    rep_val = s.repetitionValue or 0
    active_days = [days_map[i] for i in range(7) if rep_val & (1 << i)]

    def ts_to_time(ts):
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")

    # Verifica se o schedule está ativo agora
    now = datetime.now(tz=timezone.utc)
    today_bit = 1 << now.weekday()  # weekday(): 0=Seg
    day_match = bool(rep_val & today_bit) if s.repetitionMode == 1 else False
    start_time = ts_to_time(s.dateStart)
    end_time = ts_to_time(s.dateEnd)
    currently_active = False
    if s.enable and day_match and start_time and end_time:
        now_hm = now.strftime("%H:%M")
        currently_active = start_time <= now_hm <= end_time

    p = s.parameter
    return {
        "schedule_id": s.scheduleId,
        "name": s.name,
        "enable": s.enable,
        "active_days": active_days,
        "start_time": start_time,
        "end_time": end_time,
        "repetition_mode": s.repetitionMode,
        "setpoint_cool": p.setpointCool if p else None,
        "mode_ac": p.modeAC if p else None,
        "fan_speed": p.fanSpeed if p else None,
        "currently_active": currently_active,
    }


@router.post("/{device_id}/sync")
async def force_sync(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("EDITOR", "ADMIN")),
):
    from app.polling.device_poller import poll_device
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Dispositivo não encontrado")
    import asyncio
    if device.source_url is not None:
        from app.polling.external_sensors_poller import _poll_one
        asyncio.create_task(_poll_one(device))
    else:
        asyncio.create_task(poll_device(device_id, device.brise_device_id, device.is_critical_environment))
    return {"message": "Sincronização iniciada"}

@router.post("", status_code=201)
async def create_device(
    data: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    device = Device(**data.model_dump())
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return {"id": str(device.id)}

def _format_device(device, status, sector, store) -> dict:
    on_min  = status.accumulated_on_minutes  if status else None
    off_min = status.accumulated_off_minutes if status else None
    hours_on = round(on_min / 60, 1) if on_min is not None else None
    total_min = (on_min or 0) + (off_min or 0)
    uptime_pct = round(on_min / total_min * 100, 1) if total_min > 0 and on_min is not None else None
    return {
        "id": str(device.id),
        "brise_id": device.brise_device_id,
        "name": device.name,
        "sector_id": str(device.sector_id) if device.sector_id else None,
        "sector_name": sector.name if sector else None,
        "store_id": str(sector.store_id) if sector else None,
        "store_name": store.name if store else None,
        "btu": device.btu,
        "dnd": device.dnd,
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
        "hours_of_operation": hours_on,
        "uptime_pct": uptime_pct,
        "accumulated_on_minutes": on_min,
        "accumulated_off_minutes": off_min,
        "source_url": device.source_url,
        "is_external_sensor": device.source_url is not None,
        "influence_radius_m": getattr(device, 'influence_radius_m', 8),
    }

async def _get_current_parameters(device_id: uuid.UUID, brise_id: str, db: AsyncSession) -> dict:
    # Fonte de verdade para comando é a Brise. O banco é só cache do último parâmetro confirmado.
    brise_params = await brise_client.get_parameters(brise_id)
    if brise_params:
        params = _brise_params_to_dict(brise_params)
        await _persist_device_parameters(device_id, params, db)
        await db.flush()
        await set_device_params(device_id, {**params, "synced_at": datetime.utcnow().isoformat(), "source": "brise_api"})
        return params

    db_params = await _get_device_parameters_row(device_id, db)
    if db_params:
        return _db_params_to_dict(db_params)

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


# ── Sensores externos ─────────────────────────────────────────────────────────

@router.post("/external-sensor")
async def register_external_sensor(
    payload: ExternalSensorCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
):
    """
    Cadastra um sensor externo (HTTP/JSON) como dispositivo virtual.

    Body:
        name            str  obrigatório — nome exibido no painel
        source_url      str  obrigatório — URL base do sensor (ex: http://172.20.212.180)
        sector_id       str  opcional    — UUID do setor; null = sem setor
        setpoint_cool   int  opcional    — setpoint padrão (padrão: 24)
        is_critical     bool opcional    — ambiente crítico (padrão: false)
    """
    name = payload.name.strip()
    source_url = payload.source_url.strip().rstrip("/")
    if not name or not source_url:
        raise HTTPException(400, "name e source_url são obrigatórios")

    try:
        source_url = validate_sensor_url(source_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    # Identificador único derivado da URL
    ext_id = "EXT:" + source_url.replace("http://", "").replace("https://", "").replace("/", "_")

    # Verifica duplicata
    existing = await db.execute(
        select(Device).where(Device.brise_device_id == ext_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Sensor já cadastrado: {ext_id}")

    sector_id = None
    if payload.sector_id:
        sector_id = payload.sector_id

    device = Device(
        brise_device_id=ext_id,
        sector_id=sector_id,
        name=name,
        source_url=source_url,
        is_critical_environment=payload.is_critical,
        influence_radius_m=payload.influence_radius_m,
        active=True,
    )
    db.add(device)
    await db.flush()

    setpoint = payload.setpoint_cool
    db.add(DeviceParameters(device_id=device.id, setpoint_cool=setpoint))

    await db.commit()
    await db.refresh(device)

    return {
        "id": str(device.id),
        "brise_id": device.brise_device_id,
        "name": device.name,
        "source_url": device.source_url,
        "is_external_sensor": True,
        "message": "Sensor externo cadastrado. Próxima leitura no próximo ciclo de polling.",
    }
