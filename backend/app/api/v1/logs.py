"""
Logs & Rastreabilidade: endpoint unificado que combina audit_logs e zone_actions
em um feed cronológico completo de todas as ações do sistema.
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.zone import ZoneAction
from app.models.store import Store
from app.models.user import User

router = APIRouter()

# Tipos de evento que não interessam para o log operacional
_SKIP_ACTION_TYPES = {"login", "logout"}


def _audit_to_entry(a: AuditLog) -> dict:
    action_type = a.action_type or "unknown"
    if action_type == "device_control":
        extra = a.extra_data or {}
        action = extra.get("action", "")
        if "temperature" in action:
            event_type = "temperature_change"
        else:
            event_type = "device_power"
    elif action_type == "zone_mode_change":
        event_type = "mode_change"
    elif action_type == "ai_analysis":
        event_type = "ai_analysis"
    elif action_type == "kill_switch":
        event_type = "kill_switch"
    elif action_type == "zone_trigger":
        event_type = "zone_trigger"
    elif action_type == "alert_ack":
        event_type = "alert_ack"
    elif action_type == "alert_resolve":
        event_type = "alert_resolve"
    else:
        event_type = action_type

    return {
        "id": str(a.id),
        "source": "audit",
        "event_type": event_type,
        "origin": a.origin or ("ai" if action_type == "ai_analysis" else "user"),
        "created_at": a.created_at.isoformat(),
        "store_id": str(a.store_id) if a.store_id else None,
        "store_name": a.store_name,
        "zone_key": a.zone_key,
        "zone_label": None,
        "sector_name": a.sector_name,
        "device_id": str(a.device_id) if a.device_id else None,
        "device_name": a.device_name,
        "user_name": a.user_name,
        "severity": a.severity,
        "status": None,
        "summary": a.description or "",
        "old_value": a.old_value,
        "new_value": a.new_value,
        "details": a.extra_data or {},
    }


def _zone_action_to_entry(z: ZoneAction, store_name: str | None = None) -> dict:
    status = z.status or "suggestion"
    if status == "blocked":
        event_type = "guardrail_block"
        origin = "automation"
    elif status == "suggestion":
        event_type = "ai_suggestion"
        origin = "automation"
    else:
        event_type = "automation_exec"
        origin = "automation"

    zone_id = z.zone_label or z.zone_key or "—"
    device = z.device_name or "equipamento"

    # Sumário com setpoint explícito (ex: "↓ Setpoint AC Farmácia 1: 25°C → 24°C (Farmácia)")
    if event_type == "guardrail_block":
        summary = f"Bloqueio de automação — {z.block_reason or 'guardrail'} [{zone_id}]"
    elif event_type == "ai_suggestion":
        if z.setpoint_before is not None and z.setpoint_after is not None and z.setpoint_before != z.setpoint_after:
            summary = (
                f"Sugestão IA: ajuste local na zona {zone_id} — "
                f"{device} {z.setpoint_before}°C → {z.setpoint_after}°C"
            )
        elif z.device_id is not None and z.setpoint_before is not None and z.setpoint_after == z.setpoint_before:
            summary = f"Sugestão IA: ligar {device} na zona {zone_id}"
        else:
            summary = f"Sugestão IA: hotspot na zona {zone_id}"
    else:
        direction_arrow = {"down": "↓", "up": "↑"}.get(z.direction or "", "")
        sp = f"{z.setpoint_before}°C → {z.setpoint_after}°C" if z.setpoint_before and z.setpoint_after else ""
        status_icons = {
            "pending_verification": "⏳",
            "verified_success": "✓",
            "verified_failure": "✗",
        }
        icon = status_icons.get(status, "")
        summary = f"{icon} IA alterou setpoint {direction_arrow} {sp} — {device} [{zone_id}]"

    severity = None
    if status == "verified_failure":
        severity = "MEDIUM"
    elif status == "blocked":
        severity = "LOW"
    elif status == "pending_verification":
        severity = "LOW"

    return {
        "id": str(z.id),
        "source": "automation",
        "event_type": event_type,
        "origin": origin,
        "created_at": z.created_at.isoformat(),
        "store_id": str(z.store_id),
        "store_name": store_name,
        "zone_key": z.zone_key,
        "zone_label": z.zone_label,
        "sector_name": None,
        "device_id": str(z.device_id) if z.device_id else None,
        "device_name": z.device_name,
        "user_name": None,
        "severity": severity,
        "status": status,
        "summary": summary,
        "old_value": str(z.setpoint_before) if z.setpoint_before is not None else None,
        "new_value": str(z.setpoint_after) if z.setpoint_after is not None else None,
        "details": {
            "direction": z.direction,
            "temp_before": z.temp_before,
            "temp_after": z.temp_after,
            "ideal_min": z.ideal_min,
            "ideal_max": z.ideal_max,
            "setpoint_before": z.setpoint_before,
            "setpoint_after": z.setpoint_after,
            "reason": z.reason,
            "confidence": z.confidence,
            "mode": z.mode,
            "block_reason": z.block_reason,
            "suggestion_signature": getattr(z, "suggestion_signature", None),
            "verified_at": z.verified_at.isoformat() if z.verified_at else None,
        },
    }


@router.get("")
async def list_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store_id: uuid.UUID | None = None,
    zone_key: str | None = None,
    device_id: uuid.UUID | None = None,
    user_name: str | None = None,
    event_type: str | None = None,
    origin: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Retorna log unificado: audit_logs + zone_actions mesclados por timestamp."""

    # Fetch enough rows to satisfy offset+limit from both sources
    _fetch_limit = max(500, offset + limit + 50)

    # ── Audit logs ────────────────────────────────────────────────────────────
    audit_q = select(AuditLog).where(
        AuditLog.action_type.not_in(_SKIP_ACTION_TYPES)
    ).order_by(AuditLog.created_at.desc()).limit(_fetch_limit)

    if store_id:
        audit_q = audit_q.where(AuditLog.store_id == store_id)
    if zone_key:
        audit_q = audit_q.where(AuditLog.zone_key == zone_key)
    if device_id:
        audit_q = audit_q.where(AuditLog.device_id == device_id)
    if user_name:
        audit_q = audit_q.where(AuditLog.user_name.ilike(f"%{user_name}%"))
    if severity:
        audit_q = audit_q.where(AuditLog.severity == severity.upper())
    if origin:
        audit_q = audit_q.where(AuditLog.origin == origin)
    if date_from:
        audit_q = audit_q.where(AuditLog.created_at >= date_from)
    if date_to:
        audit_q = audit_q.where(AuditLog.created_at <= date_to)
    if event_type:
        type_map = {
            "temperature_change": ["device_control"],
            "device_power": ["device_control"],
            "mode_change": ["zone_mode_change"],
            "ai_analysis": ["ai_analysis"],
            "kill_switch": ["kill_switch"],
            "zone_trigger": ["zone_trigger"],
            "alert_ack": ["alert_ack"],
            "alert_resolve": ["alert_resolve"],
        }
        if event_type in type_map:
            audit_q = audit_q.where(AuditLog.action_type.in_(type_map[event_type]))
        elif event_type in ("ai_suggestion", "automation_exec", "guardrail_block"):
            audit_q = audit_q.where(AuditLog.action_type == "__none__")  # skip

    audit_result = await db.execute(audit_q)
    audit_entries = [_audit_to_entry(a) for a in audit_result.scalars().all()]

    # Post-filter event_type for device_control variants
    if event_type in ("temperature_change", "device_power"):
        audit_entries = [e for e in audit_entries if e["event_type"] == event_type]

    # ── Zone actions (com join em stores para obter store_name) ──────────────
    zone_q_with_store = (
        select(ZoneAction, Store.name.label("store_name"))
        .outerjoin(Store, ZoneAction.store_id == Store.id)
    )
    # Reaplicar filtros na query com join
    zone_q_with_store = zone_q_with_store.order_by(ZoneAction.created_at.desc()).limit(_fetch_limit)
    if store_id:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.store_id == store_id)
    if zone_key:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.zone_key == zone_key)
    if device_id:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.device_id == device_id)
    if status:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.status == status)
    if date_from:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.created_at >= date_from)
    if date_to:
        zone_q_with_store = zone_q_with_store.where(ZoneAction.created_at <= date_to)
    if event_type in ("ai_suggestion", "automation_exec", "guardrail_block"):
        status_map2 = {
            "ai_suggestion": ["suggestion"],
            "automation_exec": ["pending_verification", "verified_success", "verified_failure"],
            "guardrail_block": ["blocked"],
        }
        zone_q_with_store = zone_q_with_store.where(ZoneAction.status.in_(status_map2[event_type]))
    elif event_type and event_type not in ("ai_suggestion", "automation_exec", "guardrail_block"):
        zone_q_with_store = zone_q_with_store.where(ZoneAction.id == uuid.UUID(int=0))

    zone_result = await db.execute(zone_q_with_store)
    zone_entries = [_zone_action_to_entry(z, sname) for z, sname in zone_result.all()]

    # ── Merge + sort + paginate ───────────────────────────────────────────────
    all_entries = audit_entries + zone_entries

    if origin:
        all_entries = [e for e in all_entries if e["origin"] == origin]
    if user_name and origin != "user":
        all_entries = [e for e in all_entries if not e["user_name"] or user_name.lower() in (e["user_name"] or "").lower()]

    all_entries.sort(key=lambda x: x["created_at"], reverse=True)
    total = len(all_entries)
    page = all_entries[offset: offset + limit]

    return {"items": page, "total": total, "offset": offset, "limit": limit}


@router.get("/kpis")
async def log_kpis(
    store_id: uuid.UUID | None = None,
    zone_key: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """KPIs de rastreabilidade: contagens por tipo de evento."""

    def _zone_filter(q):
        if store_id:
            q = q.where(ZoneAction.store_id == store_id)
        if zone_key:
            q = q.where(ZoneAction.zone_key == zone_key)
        if date_from:
            q = q.where(ZoneAction.created_at >= date_from)
        if date_to:
            q = q.where(ZoneAction.created_at <= date_to)
        return q

    def _audit_filter(q):
        if store_id:
            q = q.where(AuditLog.store_id == store_id)
        if zone_key:
            q = q.where(AuditLog.zone_key == zone_key)
        if date_from:
            q = q.where(AuditLog.created_at >= date_from)
        if date_to:
            q = q.where(AuditLog.created_at <= date_to)
        return q

    # Contagens de zone_actions
    async def _count_zone(statuses: list[str]) -> int:
        q = _zone_filter(
            select(func.count(ZoneAction.id)).where(ZoneAction.status.in_(statuses))
        )
        return (await db.execute(q)).scalar() or 0

    suggestions     = await _count_zone(["suggestion"])
    auto_executed   = await _count_zone(["pending_verification", "verified_success", "verified_failure"])
    verified_ok     = await _count_zone(["verified_success"])
    verified_fail   = await _count_zone(["verified_failure"])
    guardrail_blocks = await _count_zone(["blocked"])

    # Contagens de audit_logs
    async def _count_audit(action_types: list[str], sev: str | None = None) -> int:
        q = _audit_filter(
            select(func.count(AuditLog.id)).where(AuditLog.action_type.in_(action_types))
        )
        if sev:
            q = q.where(AuditLog.severity == sev)
        return (await db.execute(q)).scalar() or 0

    manual_controls  = await _count_audit(["device_control"])
    ai_analyses      = await _count_audit(["ai_analysis"])
    mode_changes     = await _count_audit(["zone_mode_change"])
    kill_switches    = await _count_audit(["kill_switch"])
    ai_critical      = await _count_audit(["ai_analysis"], "CRITICAL")
    ai_high          = await _count_audit(["ai_analysis"], "HIGH")
    alert_acks       = await _count_audit(["alert_ack"])
    alert_resolves   = await _count_audit(["alert_resolve"])

    # Tempo médio de recuperação (verified_success com temp_before e temp_after)
    recovery_q = _zone_filter(
        select(ZoneAction.created_at, ZoneAction.verified_at)
        .where(
            ZoneAction.status == "verified_success",
            ZoneAction.verified_at.is_not(None),
        )
        .limit(200)
    )
    recovery_rows = (await db.execute(recovery_q)).all()
    if recovery_rows:
        deltas = [
            (r.verified_at - r.created_at).total_seconds() / 60
            for r in recovery_rows
            if r.verified_at and r.created_at
        ]
        avg_recovery_min = round(sum(deltas) / len(deltas), 1) if deltas else None
    else:
        avg_recovery_min = None

    # Zonas com mais intervenções (zone_actions agrupadas)
    zone_top_q = _zone_filter(
        select(ZoneAction.zone_key, ZoneAction.zone_label, func.count(ZoneAction.id).label("n"))
        .where(ZoneAction.status != "blocked")
        .group_by(ZoneAction.zone_key, ZoneAction.zone_label)
        .order_by(func.count(ZoneAction.id).desc())
        .limit(5)
    )
    zone_top = [
        {"zone_key": r.zone_key, "zone_label": r.zone_label or r.zone_key, "count": r.n}
        for r in (await db.execute(zone_top_q)).all()
    ]

    # Equipamentos com mais reincidência
    device_top_q = _zone_filter(
        select(ZoneAction.device_id, ZoneAction.device_name, func.count(ZoneAction.id).label("n"))
        .where(ZoneAction.device_id.is_not(None), ZoneAction.status != "blocked")
        .group_by(ZoneAction.device_id, ZoneAction.device_name)
        .order_by(func.count(ZoneAction.id).desc())
        .limit(5)
    )
    device_top = [
        {"device_id": str(r.device_id), "device_name": r.device_name, "count": r.n}
        for r in (await db.execute(device_top_q)).all()
    ]

    return {
        "ai_suggestions": suggestions,
        "auto_executed": auto_executed,
        "verified_success": verified_ok,
        "verified_failure": verified_fail,
        "guardrail_blocks": guardrail_blocks,
        "manual_controls": manual_controls,
        "ai_analyses": ai_analyses,
        "ai_critical": ai_critical,
        "ai_high": ai_high,
        "mode_changes": mode_changes,
        "kill_switches": kill_switches,
        "alert_acks": alert_acks,
        "alert_resolves": alert_resolves,
        "avg_recovery_minutes": avg_recovery_min,
        "top_zones": zone_top,
        "top_devices": device_top,
    }
