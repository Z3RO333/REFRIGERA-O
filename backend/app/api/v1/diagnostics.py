"""
Endpoint de diagnóstico da integração com a API Brise.
Responde perguntas como:
- Por que a Farma Matriz está sem leitura?
- Qual equipamento parou de responder?
- A API falhou ou o sensor está offline?
"""
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.device import Device, DeviceStatusLatest
from app.models.store import Store, StoreSector

router = APIRouter()

STALE_MINUTES = 15  # dado considerado desatualizado após X minutos


def _device_diag(device: Device, status: DeviceStatusLatest | None) -> dict:
    now = datetime.utcnow()

    if status is None:
        return {
            "device_id": str(device.id),
            "brise_id": device.brise_device_id,
            "name": device.name,
            "health": "NUNCA_LIDO",
            "reason": "Dispositivo nunca teve leitura registrada no sistema",
            "temperature": None,
            "last_success_at": None,
            "last_error": None,
            "last_error_at": None,
            "consecutive_failures": 0,
            "minutes_since_reading": None,
            "is_external_sensor": device.source_url is not None,
        }

    minutes_since = (now - status.updated_at).total_seconds() / 60 if status.updated_at else None
    minutes_since_success = (
        (now - status.last_success_at).total_seconds() / 60
        if status.last_success_at else None
    )

    # Determina health e motivo
    if status.consecutive_failures and status.consecutive_failures >= 3:
        health = "FALHA_API"
        reason = status.last_error or "Falhas consecutivas na API Brise"
    elif status.status_classification in {"SEM_LEITURA", "LEITURA_STALE"}:
        if status.last_error:
            health = "DADO_ATRASADO" if status.status_classification == "LEITURA_STALE" else "FALHA_API"
            reason = status.last_error
        elif minutes_since and minutes_since > STALE_MINUTES:
            health = "OFFLINE"
            reason = f"Sem comunicação há {int(minutes_since)} minutos"
        else:
            health = "SEM_LEITURA"
            reason = "Dispositivo não retornou temperatura (pode estar desligado)"
    elif status.status_classification == "DESLIGADO":
        health = "DESLIGADO"
        reason = "Equipamento desligado — aguardando leitura de temperatura"
    elif minutes_since and minutes_since > STALE_MINUTES:
        health = "DADO_ATRASADO"
        reason = f"Última leitura há {int(minutes_since)} minutos (limite: {STALE_MINUTES} min)"
    elif status.temperature is None:
        health = "SEM_TEMPERATURA"
        reason = "Aparelho responde mas não retorna temperatura"
    else:
        health = "OK"
        reason = "Leitura normal"

    return {
        "device_id": str(device.id),
        "brise_id": device.brise_device_id,
        "name": device.name,
        "health": health,
        "reason": reason,
        "temperature": status.temperature,
        "status_classification": status.status_classification,
        "state": status.state,
        "last_success_at": status.last_success_at.isoformat() if status.last_success_at else None,
        "last_error": status.last_error,
        "last_error_at": status.last_error_at.isoformat() if status.last_error_at else None,
        "consecutive_failures": status.consecutive_failures or 0,
        "minutes_since_reading": round(minutes_since, 1) if minutes_since else None,
        "minutes_since_success": round(minutes_since_success, 1) if minutes_since_success else None,
        "updated_at": status.updated_at.isoformat() if status.updated_at else None,
        "is_external_sensor": device.source_url is not None,
        "is_stale": bool(minutes_since and minutes_since > STALE_MINUTES),
    }


@router.get("/stores/{store_id}")
async def store_diagnostics(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Diagnóstico completo de uma loja.
    Retorna saúde por setor/zona e por equipamento, com motivo real de falha.
    """
    store = await db.get(Store, store_id)
    if not store:
        return {"error": "Loja não encontrada"}

    # Busca todos os devices com seus status
    result = await db.execute(
        select(Device, DeviceStatusLatest, StoreSector)
        .join(StoreSector, (Device.sector_id == StoreSector.id) & (StoreSector.store_id == store_id))
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .where(Device.active == True)
    )
    rows = result.all()

    devices_diag = []
    by_sector: dict[str, list] = {}
    now = datetime.utcnow()

    for device, status, sector in rows:
        diag = _device_diag(device, status)
        diag["sector_name"] = sector.name if sector else None
        devices_diag.append(diag)

        sector_name = sector.name if sector else "Sem setor"
        if sector_name not in by_sector:
            by_sector[sector_name] = []
        by_sector[sector_name].append(diag)

    # Resumo por setor
    sectors_summary = []
    for sector_name, devs in by_sector.items():
        ok = sum(1 for d in devs if d["health"] == "OK")
        offline = sum(1 for d in devs if d["health"] in ("OFFLINE", "FALHA_API"))
        stale = sum(1 for d in devs if d["health"] == "DADO_ATRASADO")
        no_reading = sum(1 for d in devs if d["health"] in ("SEM_LEITURA", "SEM_TEMPERATURA", "NUNCA_LIDO"))
        off = sum(1 for d in devs if d["health"] == "DESLIGADO")

        if offline > 0 or (offline + no_reading) == len(devs):
            sector_health = "CRÍTICO"
        elif stale > 0 or no_reading > 0:
            sector_health = "PARCIAL"
        else:
            sector_health = "OK"

        temps = [d["temperature"] for d in devs if d["temperature"] is not None]
        sectors_summary.append({
            "sector_name": sector_name,
            "health": sector_health,
            "total": len(devs),
            "ok": ok,
            "offline": offline,
            "stale": stale,
            "no_reading": no_reading,
            "off": off,
            "avg_temp": round(sum(temps) / len(temps), 1) if temps else None,
            "devices": devs,
        })

    # KPIs gerais
    total = len(devices_diag)
    n_ok = sum(1 for d in devices_diag if d["health"] == "OK")
    n_offline = sum(1 for d in devices_diag if d["health"] in ("OFFLINE", "FALHA_API"))
    n_stale = sum(1 for d in devices_diag if d["health"] == "DADO_ATRASADO")
    n_no_read = sum(1 for d in devices_diag if d["health"] in ("SEM_LEITURA", "SEM_TEMPERATURA", "NUNCA_LIDO"))
    n_off = sum(1 for d in devices_diag if d["health"] == "DESLIGADO")
    n_failures = [d["consecutive_failures"] for d in devices_diag]

    worst = sorted(
        [d for d in devices_diag if d["health"] not in ("OK", "DESLIGADO")],
        key=lambda d: (d["consecutive_failures"], d.get("minutes_since_reading") or 0),
        reverse=True,
    )[:5]

    return {
        "store_id": str(store_id),
        "store_name": store.name,
        "generated_at": now.isoformat(),
        "summary": {
            "total_devices": total,
            "ok": n_ok,
            "offline": n_offline,
            "stale": n_stale,
            "no_reading": n_no_read,
            "off": n_off,
            "max_consecutive_failures": max(n_failures) if n_failures else 0,
            "overall_health": (
                "CRÍTICO" if n_offline > total * 0.5
                else "DEGRADADO" if n_offline > 0 or n_stale > total * 0.3
                else "PARCIAL" if n_no_read > 0 or n_stale > 0
                else "OK"
            ),
        },
        "worst_devices": worst,
        "sectors": sorted(sectors_summary, key=lambda s: s["sector_name"]),
    }


@router.get("/devices/{device_id}")
async def device_diagnostics(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """Diagnóstico individual de um equipamento."""
    device = await db.get(Device, device_id)
    if not device:
        return {"error": "Equipamento não encontrado"}
    status = await db.get(DeviceStatusLatest, device_id)
    return _device_diag(device, status)
