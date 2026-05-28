"""
API de aprendizado adaptativo da IA.

Endpoints:
  POST /learning/decisions/{decision_id}/feedback  — operador aprova/rejeita/modifica
  GET  /learning/stats                             — dashboard global de aprovação/sucesso
  GET  /learning/stats/{store_id}                  — stats por loja
  GET  /learning/scores                            — learning scores agregados
  GET  /learning/decisions                         — histórico de decisões com contexto
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.auth.dependencies import get_current_user
from app.models.learning import AIDecision, AIDecisionFeedback, AIDecisionOutcome, AILearningScore
from app.services.learning_service import (
    record_feedback,
    get_learning_stats,
    get_zone_learning_context,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["learning"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FeedbackIn(BaseModel):
    feedback_type: Literal["approved", "rejected", "modified"]
    actual_action_type: str | None = None
    actual_device_id: uuid.UUID | None = None
    actual_device_name: str | None = None
    actual_setpoint_to: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/decisions/{decision_id}/feedback")
async def submit_feedback(
    decision_id: uuid.UUID,
    body: FeedbackIn,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Operador aprova, rejeita ou modifica uma sugestão da IA."""
    decision = await db.get(AIDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Decisão não encontrada")

    fb = await record_feedback(
        decision_id=decision_id,
        feedback_type=body.feedback_type,
        operator_name=getattr(current_user, "name", None),
        operator_email=getattr(current_user, "email", None),
        actual_action_type=body.actual_action_type,
        actual_device_id=body.actual_device_id,
        actual_device_name=body.actual_device_name,
        actual_setpoint_to=body.actual_setpoint_to,
        session=db,
    )
    if fb is None:
        raise HTTPException(status_code=409, detail="Feedback já registrado para esta decisão")

    await db.commit()
    return {"ok": True, "feedback_type": body.feedback_type, "decision_id": str(decision_id)}


@router.get("/stats")
async def learning_stats_global(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard global: taxa de aprovação, taxa de sucesso, médias."""
    return await get_learning_stats(store_id=None, session=db, days=days)


@router.get("/stats/{store_id}")
async def learning_stats_store(
    store_id: uuid.UUID,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard por loja."""
    return await get_learning_stats(store_id=store_id, session=db, days=days)


@router.get("/scores")
async def learning_scores(
    scope: str = Query("zone", regex="^(zone|device|store|global)$"),
    scope_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Retorna learning scores por contexto."""
    q = select(AILearningScore).where(AILearningScore.scope == scope)
    if scope_id:
        q = q.where(AILearningScore.scope_id == scope_id)
    q = q.order_by(desc(AILearningScore.sample_count))
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "scope": r.scope,
            "scope_id": r.scope_id,
            "action_type": r.action_type,
            "thermal_status": r.thermal_status,
            "approval_rate": r.approval_rate,
            "success_rate": r.success_rate,
            "avg_delta_30m": r.avg_delta_30m,
            "sample_count": r.sample_count,
            "confidence": r.confidence,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/decisions")
async def list_decisions(
    store_id: uuid.UUID | None = None,
    zone_key: str | None = None,
    decision_type: str | None = None,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Histórico de decisões com feedback e outcome."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = (
        select(AIDecision, AIDecisionFeedback, AIDecisionOutcome)
        .outerjoin(AIDecisionFeedback, AIDecisionFeedback.decision_id == AIDecision.id)
        .outerjoin(AIDecisionOutcome, AIDecisionOutcome.decision_id == AIDecision.id)
        .where(AIDecision.created_at >= cutoff)
    )
    if store_id:
        q = q.where(AIDecision.store_id == store_id)
    if zone_key:
        q = q.where(AIDecision.zone_key == zone_key)
    if decision_type:
        q = q.where(AIDecision.decision_type == decision_type)
    q = q.order_by(desc(AIDecision.created_at)).limit(limit)

    result = await db.execute(q)
    rows = result.all()

    items = []
    for decision, feedback, outcome in rows:
        # Contexto de aprendizado para explicação ao operador
        learning_ctx = None
        if decision.action_type and decision.thermal_status:
            learning_ctx = await get_zone_learning_context(
                zone_key=decision.zone_key,
                action_type=decision.action_type,
                thermal_status=decision.thermal_status or "WARM",
                session=db,
            )
        items.append({
            "id": str(decision.id),
            "zone_action_id": str(decision.zone_action_id) if decision.zone_action_id else None,
            "store_id": str(decision.store_id),
            "zone_key": decision.zone_key,
            "zone_label": decision.zone_label,
            "decision_type": decision.decision_type,
            "thermal_status": decision.thermal_status,
            "avg_temp": decision.avg_temp,
            "ideal_min": decision.ideal_min,
            "ideal_max": decision.ideal_max,
            "trend_c_per_hour": decision.trend_c_per_hour,
            "devices_on": decision.devices_on,
            "devices_off": decision.devices_off,
            "had_hotspot": decision.had_hotspot,
            "hotspot_peak_temp": decision.hotspot_peak_temp,
            "action_type": decision.action_type,
            "device_name": decision.device_name,
            "setpoint_from": decision.setpoint_from,
            "setpoint_to": decision.setpoint_to,
            "confidence": decision.confidence,
            "energy_strategy": decision.energy_strategy,
            "thermal_impact_score": decision.thermal_impact_score,
            "final_score": decision.final_score,
            "learning_bonus_applied": decision.learning_bonus_applied,
            "created_at": decision.created_at.isoformat(),
            "feedback": {
                "type": feedback.feedback_type,
                "operator": feedback.operator_name,
                "actual_setpoint_to": feedback.actual_setpoint_to,
                "at": feedback.feedback_at.isoformat(),
            } if feedback else None,
            "outcome": {
                "success_score": outcome.success_score,
                "delta_15m": outcome.delta_15m,
                "delta_30m": outcome.delta_30m,
                "delta_60m": outcome.delta_60m,
                "status_60m": outcome.status_60m,
                "completed": outcome.completed,
            } if outcome else None,
            "learning_context": learning_ctx,
        })

    return {"items": items, "total": len(items)}


@router.get("/zone-context/{zone_key}")
async def zone_learning_context(
    zone_key: str,
    action_type: str = Query("setpoint_down"),
    thermal_status: str = Query("WARM"),
    db: AsyncSession = Depends(get_db),
):
    """Retorna contexto de aprendizado para uma zona específica.

    Usado para exibir 'estou sugerindo isso porque funciona X% das vezes'.
    """
    ctx = await get_zone_learning_context(
        zone_key=zone_key,
        action_type=action_type,
        thermal_status=thermal_status,
        session=db,
    )
    return ctx or {"explanation": None, "sample_count": 0}
