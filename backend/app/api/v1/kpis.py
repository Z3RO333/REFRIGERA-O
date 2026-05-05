import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.device import DeviceStatusLatest, Device
from app.models.alert import Alert
from app.models.store import Store, StoreSector

router = APIRouter()

@router.get("/summary")
async def get_kpi_summary(
    store_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(
            func.count(DeviceStatusLatest.device_id).label("total"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "NORMAL").label("normal"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "ATENÇÃO").label("warning"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "CRÍTICO").label("critical"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "SEM_LEITURA").label("no_reading"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "BAIXA_EFICIÊNCIA").label("low_eff"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "DESLIGADO").label("off"),
            func.avg(DeviceStatusLatest.temperature).filter(DeviceStatusLatest.state == True).label("avg_temp"),
            func.avg(DeviceStatusLatest.efficiency_score).filter(DeviceStatusLatest.state == True).label("avg_eff"),
        )
        .join(Device, DeviceStatusLatest.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .where(Device.active == True)
    )
    if store_id:
        query = query.where(StoreSector.store_id == store_id)

    result = await db.execute(query)
    row = result.first()

    alerts_query = (
        select(
            func.count(Alert.id).filter(Alert.severity == "P1", Alert.status == "OPEN").label("p1"),
            func.count(Alert.id).filter(Alert.severity == "P2", Alert.status == "OPEN").label("p2"),
        )
        .join(Device, Alert.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .where(Device.active == True)
    )
    if store_id:
        alerts_query = alerts_query.where(StoreSector.store_id == store_id)

    alerts_result = await db.execute(alerts_query)
    alerts_row = alerts_result.first()
    total = row.total or 0
    normal = row.normal or 0
    online = total - (row.no_reading or 0) - (row.off or 0)
    compliance = (normal / online * 100) if online > 0 else None
    return {
        "store_id": str(store_id) if store_id else None,
        "total_devices": total,
        "devices_normal": normal,
        "devices_warning": row.warning or 0,
        "devices_critical": row.critical or 0,
        "devices_no_reading": row.no_reading or 0,
        "devices_low_efficiency": row.low_eff or 0,
        "devices_off": row.off or 0,
        "devices_online": online,
        "alerts_p1_open": alerts_row.p1 or 0 if alerts_row else 0,
        "alerts_p2_open": alerts_row.p2 or 0 if alerts_row else 0,
        "avg_temperature": float(row.avg_temp) if row.avg_temp else None,
        "avg_efficiency_score": float(row.avg_eff) if row.avg_eff else None,
        "compliance_rate": round(compliance, 1) if compliance else None,
    }

@router.get("/stores/{store_id}")
async def get_store_kpis(store_id: str, db: AsyncSession = Depends(get_db)):
    import uuid as _uuid
    sid = _uuid.UUID(store_id)
    result = await db.execute(
        select(
            Store.name,
            func.count(DeviceStatusLatest.device_id).label("total"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "NORMAL").label("normal"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "ATENÇÃO").label("warning"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "CRÍTICO").label("critical"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "SEM_LEITURA").label("no_reading"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "BAIXA_EFICIÊNCIA").label("low_eff"),
            func.count(DeviceStatusLatest.device_id).filter(DeviceStatusLatest.status_classification == "DESLIGADO").label("off"),
            func.avg(DeviceStatusLatest.temperature).filter(DeviceStatusLatest.state == True).label("avg_temp"),
        )
        .join(Device, DeviceStatusLatest.device_id == Device.id)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .join(Store, StoreSector.store_id == Store.id)
        .where(StoreSector.store_id == sid, Device.active == True)
        .group_by(Store.name)
    )
    row = result.first()
    if not row:
        return {"store_id": store_id, "total_devices": 0}
    online = (row.total or 0) - (row.no_reading or 0) - (row.off or 0)
    compliance = ((row.normal or 0) / online * 100) if online > 0 else None
    return {
        "store_id": store_id,
        "store_name": row.name,
        "total_devices": row.total or 0,
        "devices_normal": row.normal or 0,
        "devices_warning": row.warning or 0,
        "devices_critical": row.critical or 0,
        "devices_no_reading": row.no_reading or 0,
        "devices_low_efficiency": row.low_eff or 0,
        "devices_off": row.off or 0,
        "devices_online": online,
        "avg_temperature": float(row.avg_temp) if row.avg_temp else None,
        "compliance_rate": round(compliance, 1) if compliance else None,
    }
