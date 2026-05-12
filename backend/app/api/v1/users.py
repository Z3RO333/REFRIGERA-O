import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.user import User
from app.api.v1.auth import get_current_user

router = APIRouter()

VALID_ROLES = {"VIEWER", "EDITOR", "ADMIN"}


def _user_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "active": u.active,
        "created_at": u.created_at.isoformat(),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return [_user_dict(u) for u in result.scalars().all()]


@router.put("/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Apenas administradores podem alterar perfis")
    if current_user.id == user_id:
        raise HTTPException(400, "Não é possível alterar o próprio perfil")

    role = data.get("role", "")
    if role not in VALID_ROLES:
        raise HTTPException(400, f"Perfil inválido. Use: {', '.join(VALID_ROLES)}")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    user.role = role
    await db.commit()
    return _user_dict(user)


@router.put("/{user_id}/active")
async def toggle_user_active(
    user_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.role != "ADMIN":
        raise HTTPException(403, "Apenas administradores podem ativar/desativar usuários")
    if current_user.id == user_id:
        raise HTTPException(400, "Não é possível desativar a própria conta")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Usuário não encontrado")

    user.active = bool(data.get("active", True))
    await db.commit()
    return _user_dict(user)
