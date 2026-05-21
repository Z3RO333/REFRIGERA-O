import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.api.v1.auth import require_role

router = APIRouter()


def _log_dict(a: AuditLog) -> dict:
    return {
        "id": str(a.id),
        "user_id": str(a.user_id) if a.user_id else None,
        "user_name": a.user_name,
        "user_email": a.user_email,
        "action_type": a.action_type,
        "origin": a.origin,
        "severity": a.severity,
        "store_id": str(a.store_id) if a.store_id else None,
        "store_name": a.store_name,
        "device_id": str(a.device_id) if a.device_id else None,
        "device_name": a.device_name,
        "sector_name": a.sector_name,
        "zone_key": a.zone_key,
        "description": a.description,
        "old_value": a.old_value,
        "new_value": a.new_value,
        "extra_data": a.extra_data,
        "created_at": a.created_at.isoformat(),
    }


@router.get("")
async def list_audit(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action_type: str | None = None,
    origin: str | None = None,
    severity: str | None = None,
    store_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
    user_name: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("ADMIN")),
) -> dict:
    q = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_q = select(func.count(AuditLog.id))

    if action_type:
        q = q.where(AuditLog.action_type == action_type)
        count_q = count_q.where(AuditLog.action_type == action_type)
    if origin:
        q = q.where(AuditLog.origin == origin)
        count_q = count_q.where(AuditLog.origin == origin)
    if severity:
        q = q.where(AuditLog.severity == severity.upper())
        count_q = count_q.where(AuditLog.severity == severity.upper())
    if store_id:
        q = q.where(AuditLog.store_id == store_id)
        count_q = count_q.where(AuditLog.store_id == store_id)
    if device_id:
        q = q.where(AuditLog.device_id == device_id)
        count_q = count_q.where(AuditLog.device_id == device_id)
    if user_name:
        q = q.where(AuditLog.user_name.ilike(f"%{user_name}%"))
        count_q = count_q.where(AuditLog.user_name.ilike(f"%{user_name}%"))

    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(q.offset(offset).limit(limit))
    items = [_log_dict(a) for a in result.scalars().all()]

    return {"items": items, "total": total, "offset": offset, "limit": limit}
