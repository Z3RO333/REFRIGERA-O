import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Header, Query
from jose import jwt, JWTError
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.db.session import get_db
from app.models.alert import Alert
from app.models.device import Device
from app.models.store import StoreSector, Store
from app.schemas.alert import AlertAck


def _extract_user_email(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        return "operator"
    try:
        token = authorization.removeprefix("Bearer ")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload.get("email") or "operator"
    except JWTError:
        return "operator"

router = APIRouter()

@router.get("")
async def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    store_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Alert, Device, StoreSector, Store)
        .join(Device, Alert.device_id == Device.id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
    )
    conditions = []
    if status:
        conditions.append(Alert.status == status)
    if severity:
        severities = severity.split(",")
        conditions.append(Alert.severity.in_(severities))
    if store_id:
        conditions.append(StoreSector.store_id == store_id)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(Alert.opened_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()
    alerts = []
    for alert, device, sector, store in rows:
        alerts.append({
            "id": str(alert.id),
            "device_id": str(alert.device_id),
            "brise_id": device.brise_device_id,
            "device_name": device.name,
            "store_name": store.name if store else None,
            "sector_name": sector.name if sector else None,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "status": alert.status,
            "temperature_at_alert": alert.temperature_at_alert,
            "setpoint_at_alert": alert.setpoint_at_alert,
            "delta_at_alert": alert.delta_at_alert,
            "message": alert.message,
            "opened_at": alert.opened_at.isoformat(),
            "acked_at": alert.acked_at.isoformat() if alert.acked_at else None,
            "acked_by": alert.acked_by,
            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        })
    return {"alerts": alerts, "page": page, "per_page": per_page}

@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
    body: AlertAck,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    alert = await db.get(Alert, alert_id)
    if not alert:
        from fastapi import HTTPException
        raise HTTPException(404, "Alerta não encontrado")
    alert.status = "ACK"
    alert.acked_at = datetime.utcnow()
    alert.acked_by = _extract_user_email(authorization)
    if body.notes:
        alert.notes = body.notes
    await db.commit()
    return {"message": "Alerta reconhecido"}

@router.post("/{alert_id}/resolve")
async def resolve_alert(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        from fastapi import HTTPException
        raise HTTPException(404, "Alerta não encontrado")
    alert.status = "RESOLVED"
    alert.resolved_at = datetime.utcnow()
    await db.commit()
    return {"message": "Alerta resolvido"}
