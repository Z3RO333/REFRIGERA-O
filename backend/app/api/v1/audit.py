import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.audit import AuditLog
from app.api.v1.auth import get_current_user
from app.models.user import User

router = APIRouter()


def _log_dict(a: AuditLog) -> dict:
    return {
        "id": str(a.id),
        "user_id": str(a.user_id) if a.user_id else None,
        "user_name": a.user_name,
        "user_email": a.user_email,
        "action_type": a.action_type,
        "store_id": str(a.store_id) if a.store_id else None,
        "device_id": str(a.device_id) if a.device_id else None,
        "device_name": a.device_name,
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
    action_type: str | None = None,
    store_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action_type:
        q = q.where(AuditLog.action_type == action_type)
    if store_id:
        q = q.where(AuditLog.store_id == store_id)
    result = await db.execute(q)
    return [_log_dict(a) for a in result.scalars().all()]
