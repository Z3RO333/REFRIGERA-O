"""
Controle global da automação de zonas.
Expõe kill switch e status agregado.
"""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import redis_client
from app.db.session import get_db, AsyncSessionLocal
from app.models.zone import ZoneAction, ZoneAutomation
from app.models.audit import AuditLog
from app.models.user import User
from app.api.v1.auth import require_role
from app.services.zone_controller import KILL_SWITCH_KEY
from app.schemas.automation import KillSwitchUpdate

router = APIRouter()

_KS_AT_KEY = "automation:kill_switch_at"
_KS_BY_KEY = "automation:kill_switch_by"


@router.get("/status")
async def automation_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Estado global da automação: kill switch + contagens."""
    kill_active = await redis_client.exists(KILL_SWITCH_KEY)
    kill_at = await redis_client.get(_KS_AT_KEY)
    kill_by = await redis_client.get(_KS_BY_KEY)

    # Contagem de zonas por modo
    result = await db.execute(
        select(ZoneAutomation.mode, func.count(ZoneAutomation.id).label("n"))
        .group_by(ZoneAutomation.mode)
    )
    mode_counts: dict[str, int] = {row.mode: row.n for row in result.all()}

    # Ações executadas hoje
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    executed_today = await db.execute(
        select(func.count(ZoneAction.id)).where(
            ZoneAction.status.in_(["pending_verification", "verified_success", "verified_failure"]),
            ZoneAction.created_at >= today,
        )
    )

    return {
        "kill_switch_active": kill_active,
        "kill_switch_activated_at": kill_at,
        "kill_switch_activated_by": kill_by,
        "mode_counts": mode_counts,
        "executed_today": executed_today.scalar() or 0,
    }


@router.post("/kill-switch")
async def set_kill_switch(
    data: KillSwitchUpdate,
    current_user: User = Depends(require_role("ADMIN")),
) -> dict:
    """Ativa ou desativa o kill switch global. Body: { active: bool }"""
    activate = data.active
    activated_by: str = current_user.name

    if activate:
        await redis_client.set(KILL_SWITCH_KEY, "1")
        await redis_client.set(_KS_AT_KEY, datetime.utcnow().isoformat())
        await redis_client.set(_KS_BY_KEY, activated_by)
    else:
        await redis_client.delete(KILL_SWITCH_KEY)
        await redis_client.delete(_KS_AT_KEY)
        await redis_client.delete(_KS_BY_KEY)

    try:
        async with AsyncSessionLocal() as session:
            session.add(AuditLog(
                action_type="kill_switch",
                origin="user",
                severity="HIGH" if activate else "LOW",
                description=f"Kill switch {'ATIVADO' if activate else 'DESATIVADO'} por {activated_by}",
                user_id=current_user.id,
                user_name=activated_by,
                user_email=current_user.email,
                extra_data={"active": activate, "by": activated_by},
            ))
            await session.commit()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Falha ao auditar kill switch: %s", exc)

    await redis_client.publish("automation.kill_switch.changed", {
        "active": activate,
        "by": activated_by,
        "at": datetime.utcnow().isoformat(),
    })

    return {"kill_switch_active": activate, "by": activated_by}
