import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditLog
from app.models.user import User


async def log_action(
    db: AsyncSession,
    action_type: str,
    description: str,
    user: User | None = None,
    store_id: uuid.UUID | None = None,
    store_name: str | None = None,
    device_id: uuid.UUID | None = None,
    device_name: str | None = None,
    zone_key: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    extra_data: dict | None = None,
    origin: str | None = None,
    severity: str | None = None,
    sector_name: str | None = None,
    store_name: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_name=user.name if user else None,
        user_email=user.email if user else None,
        action_type=action_type,
        store_id=store_id,
        device_id=device_id,
        device_name=device_name,
        zone_key=zone_key,
        description=description,
        old_value=old_value,
        new_value=new_value,
        extra_data=extra_data,
        origin=origin or ("user" if user else "system"),
        severity=severity,
        sector_name=sector_name,
        store_name=store_name or None,
    )
    db.add(entry)
    # O commit é responsabilidade do chamador junto com as demais alterações
