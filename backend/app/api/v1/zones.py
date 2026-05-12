import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import redis_client
from app.db.session import get_db
from app.models.zone import ZoneAction, ZoneAutomation
from app.models.user import User
from app.api.v1.auth import get_current_user
from app.services.audit_service import log_action
from app.services.zone_controller import (
    KILL_SWITCH_KEY,
    ZONE_COOLDOWN_SECONDS,
    ZONES,
    _check_guardrails,
    _classify,
    _consecutive_failures,
    _daily_count,
    _evaluate_zone,
    get_or_create_automation,
    get_zone_last_action,
)

router = APIRouter()


def _cooldown_key(store_id: uuid.UUID, zone_key: str) -> str:
    return f"zone:cooldown:{store_id}:{zone_key}"


async def _cooldown_ttl(store_id: uuid.UUID, zone_key: str) -> int | None:
    ttl = await redis_client.ttl(_cooldown_key(store_id, zone_key))
    return ttl if ttl and ttl > 0 else None


def _action_dict(a: ZoneAction) -> dict:
    return {
        "id": str(a.id),
        "zone_key": a.zone_key,
        "zone_label": a.zone_label,
        "device_id": str(a.device_id) if a.device_id else None,
        "device_name": a.device_name,
        "direction": a.direction,
        "temp_before": a.temp_before,
        "temp_after": a.temp_after,
        "ideal_min": a.ideal_min,
        "ideal_max": a.ideal_max,
        "setpoint_before": a.setpoint_before,
        "setpoint_after": a.setpoint_after,
        "reason": a.reason,
        "confidence": a.confidence,
        "mode": a.mode,
        "status": a.status,
        "block_reason": a.block_reason,
        "attempt_count": a.attempt_count,
        "created_at": a.created_at.isoformat(),
        "verified_at": a.verified_at.isoformat() if a.verified_at else None,
    }


@router.get("/{store_id}")
async def list_zones(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Retorna estado de automação de todas as zonas conhecidas para a loja."""
    result = await db.execute(
        select(ZoneAutomation).where(ZoneAutomation.store_id == store_id)
    )
    existing: dict[str, ZoneAutomation] = {a.zone_key: a for a in result.scalars().all()}

    zones_out: list[dict] = []
    for zone_key, zone_cfg in ZONES.items():
        automation = existing.get(zone_key)

        last_action = await get_zone_last_action(store_id, zone_key, db)
        cooldown_ttl = await _cooldown_ttl(store_id, zone_key)
        daily_count = await _daily_count(store_id, zone_key, db)
        consecutive_fail = await _consecutive_failures(store_id, zone_key, db)

        # Guardrail: verifica se a automação está bloqueada no momento
        guardrail_reason: str | None = None
        if automation and automation.mode not in ("manual",):
            guardrail_reason = await _check_guardrails(automation)

        zones_out.append({
            "zone_key": zone_key,
            "zone_label": zone_cfg.label,
            "zone_type": zone_cfg.zone_type,  # ABERTA | SALA_FECHADA
            "sector_names": zone_cfg.sector_names,
            "ideal_min": zone_cfg.ideal_min,
            "ideal_max": zone_cfg.ideal_max,
            "mode": automation.mode if automation else "manual",
            "setpoint_min": automation.setpoint_min if automation else 18,
            "setpoint_max": automation.setpoint_max if automation else 28,
            "max_daily_adjustments": automation.max_daily_adjustments if automation else 6,
            "daily_count": daily_count,
            "consecutive_failures": consecutive_fail,
            "cooldown_remaining_s": cooldown_ttl,
            "last_action": _action_dict(last_action) if last_action else None,
            # Guardrails
            "allowed_start_hour": automation.allowed_start_hour if automation else 7,
            "allowed_start_minute": automation.allowed_start_minute if automation else 30,
            "allowed_end_hour": automation.allowed_end_hour if automation else 18,
            "allowed_end_minute": automation.allowed_end_minute if automation else 30,
            "is_critical_zone": automation.is_critical_zone if automation else False,
            "guardrail_active": guardrail_reason is not None,
            "guardrail_reason": guardrail_reason,
            # Confiança de leitura: baixa se SALA_FECHADA sem sensor interno
            "reading_confidence": automation.reading_confidence if automation else 1.0,
        })

    return zones_out


@router.put("/{store_id}/{zone_key}/mode")
async def set_zone_mode(
    store_id: uuid.UUID,
    zone_key: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Altera o modo de automação de uma zona (manual|suggestion|semi|auto)."""
    mode = data.get("mode", "manual")
    valid_modes = {"manual", "suggestion", "semi", "auto"}
    if mode not in valid_modes:
        raise HTTPException(400, f"Modo inválido. Use: {', '.join(valid_modes)}")

    if zone_key not in ZONES:
        raise HTTPException(404, "Zona não encontrada")

    automation = await get_or_create_automation(store_id, zone_key, db)
    old_mode = automation.mode
    automation.mode = mode

    if "setpoint_min" in data:
        automation.setpoint_min = int(data["setpoint_min"])
    if "setpoint_max" in data:
        automation.setpoint_max = int(data["setpoint_max"])
    if "max_daily_adjustments" in data:
        automation.max_daily_adjustments = int(data["max_daily_adjustments"])

    zone_label = ZONES[zone_key].label if zone_key in ZONES else zone_key
    await log_action(
        db, "zone_mode_change",
        f"Modo da zona '{zone_label}' alterado: {old_mode} → {mode}",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
        old_value=old_mode,
        new_value=mode,
    )
    await db.commit()
    return {"zone_key": zone_key, "mode": mode}


@router.get("/{store_id}/{zone_key}/history")
async def zone_history(
    store_id: uuid.UUID,
    zone_key: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Retorna os últimos N registros de ações da zona."""
    if zone_key not in ZONES:
        raise HTTPException(404, "Zona não encontrada")

    result = await db.execute(
        select(ZoneAction)
        .where(ZoneAction.store_id == store_id, ZoneAction.zone_key == zone_key)
        .order_by(ZoneAction.created_at.desc())
        .limit(min(limit, 100))
    )
    return [_action_dict(a) for a in result.scalars().all()]


@router.post("/{store_id}/{zone_key}/trigger")
async def trigger_zone(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispara avaliação manual de uma zona (ignora cooldown)."""
    if zone_key not in ZONES:
        raise HTTPException(404, "Zona não encontrada")

    automation = await get_or_create_automation(store_id, zone_key, db)
    await db.commit()

    # Remove cooldown para permitir disparo imediato
    await redis_client.delete(_cooldown_key(store_id, zone_key))

    try:
        await _evaluate_zone(automation)
    except Exception as exc:
        raise HTTPException(500, f"Erro ao avaliar zona: {exc}")

    last_action = await get_zone_last_action(store_id, zone_key, db)
    return {
        "triggered": True,
        "last_action": _action_dict(last_action) if last_action else None,
    }


@router.put("/{store_id}/{zone_key}/guardrails")
async def update_zone_guardrails(
    store_id: uuid.UUID,
    zone_key: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Atualiza guardrails de uma zona (horário, zona crítica)."""
    if zone_key not in ZONES:
        raise HTTPException(404, "Zona não encontrada")

    automation = await get_or_create_automation(store_id, zone_key, db)

    def _parse_time(val: str) -> tuple[int, int]:
        try:
            parts = str(val).split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            return h, m
        except (ValueError, IndexError):
            raise HTTPException(400, f"Horário inválido '{val}'. Use formato HH:MM (ex: 07:30)")

    if "allowed_start_time" in data:
        h, m = _parse_time(data["allowed_start_time"])
        automation.allowed_start_hour, automation.allowed_start_minute = h, m

    if "allowed_end_time" in data:
        h, m = _parse_time(data["allowed_end_time"])
        automation.allowed_end_hour, automation.allowed_end_minute = h, m

    if "is_critical_zone" in data:
        automation.is_critical_zone = bool(data["is_critical_zone"])

    start_total = automation.allowed_start_hour * 60 + automation.allowed_start_minute
    end_total   = automation.allowed_end_hour   * 60 + automation.allowed_end_minute
    if start_total >= end_total:
        raise HTTPException(400, "Horário de início deve ser anterior ao de fim")

    await db.commit()
    return {
        "zone_key": zone_key,
        "allowed_start_time": f"{automation.allowed_start_hour:02d}:{automation.allowed_start_minute:02d}",
        "allowed_end_time":   f"{automation.allowed_end_hour:02d}:{automation.allowed_end_minute:02d}",
        "is_critical_zone": automation.is_critical_zone,
    }
