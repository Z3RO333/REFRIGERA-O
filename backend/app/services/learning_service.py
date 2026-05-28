"""
Serviço de aprendizado adaptativo da IA.

Fluxo completo:
  1. record_decision()  — chamado pelo zone_controller ao tomar cada decisão
  2. record_feedback()  — chamado pela API quando operador aprova/rejeita/modifica
  3. measure_outcomes() — job agendado que mede T+15/30/60 e calcula success_score
  4. update_learning_scores() — agrega outcomes em learning scores por contexto
  5. get_learning_bonus() — consultado pelo zone_controller ao ranquear candidatos
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.learning import (
    AIDecision, AIDecisionFeedback, AIDecisionOutcome, AILearningScore,
)

logger = logging.getLogger(__name__)

# Mínimo de amostras para aplicar bônus de aprendizado
MIN_SAMPLES = 10
# Bônus máximo/mínimo (pontos no thermal_impact_score)
MAX_BONUS = 12.0
MIN_BONUS = -12.0
# Decaimento temporal: amostras com mais de N dias pesam menos
DECAY_DAYS = 90


# ── 1. Registrar decisão ──────────────────────────────────────────────────────

async def record_decision(
    *,
    session: AsyncSession,
    zone_action_id: uuid.UUID | None,
    store_id: uuid.UUID,
    zone_key: str,
    zone_label: str | None,
    decision_type: str,
    thermal_status: str | None,
    avg_temp: float | None,
    ideal_min: float | None,
    ideal_max: float | None,
    trend_c_per_hour: float | None,
    freshness_ratio: float | None,
    devices_on: int | None,
    devices_off: int | None,
    had_hotspot: bool,
    hotspot_peak_temp: float | None,
    action_type: str | None,
    device_id: uuid.UUID | None,
    device_name: str | None,
    setpoint_from: int | None,
    setpoint_to: int | None,
    fan_speed_from: int | None,
    fan_speed_to: int | None,
    confidence: float | None,
    energy_strategy: str | None,
    thermal_impact_score: float | None,
    energy_cost_score: float | None,
    final_score: float | None,
    learning_bonus_applied: float | None = None,
) -> AIDecision:
    decision = AIDecision(
        zone_action_id=zone_action_id,
        store_id=store_id,
        zone_key=zone_key,
        zone_label=zone_label,
        decision_type=decision_type,
        thermal_status=thermal_status,
        avg_temp=avg_temp,
        ideal_min=ideal_min,
        ideal_max=ideal_max,
        trend_c_per_hour=trend_c_per_hour,
        freshness_ratio=freshness_ratio,
        devices_on=devices_on,
        devices_off=devices_off,
        had_hotspot=had_hotspot,
        hotspot_peak_temp=hotspot_peak_temp,
        action_type=action_type,
        device_id=device_id,
        device_name=device_name,
        setpoint_from=setpoint_from,
        setpoint_to=setpoint_to,
        fan_speed_from=fan_speed_from,
        fan_speed_to=fan_speed_to,
        confidence=confidence,
        energy_strategy=energy_strategy,
        thermal_impact_score=thermal_impact_score,
        energy_cost_score=energy_cost_score,
        final_score=final_score,
        learning_bonus_applied=learning_bonus_applied,
    )
    session.add(decision)
    await session.flush()  # garante que decision.id existe

    # Cria registro de outcome vazio para medir T+15/30/60 depois
    outcome = AIDecisionOutcome(
        decision_id=decision.id,
        temp_before=avg_temp,
        status_before=thermal_status,
    )
    session.add(outcome)

    # Feedback automático para ações executadas automaticamente
    if decision_type == "auto":
        feedback = AIDecisionFeedback(
            decision_id=decision.id,
            feedback_type="auto_executed",
        )
        session.add(feedback)

    return decision


# ── 2. Registrar feedback do operador ────────────────────────────────────────

async def record_feedback(
    *,
    decision_id: uuid.UUID,
    feedback_type: str,
    operator_name: str | None,
    operator_email: str | None,
    actual_action_type: str | None = None,
    actual_device_id: uuid.UUID | None = None,
    actual_device_name: str | None = None,
    actual_setpoint_to: int | None = None,
    session: AsyncSession,
) -> AIDecisionFeedback | None:
    existing = await session.execute(
        select(AIDecisionFeedback).where(AIDecisionFeedback.decision_id == decision_id)
    )
    if existing.scalar_one_or_none():
        logger.warning("record_feedback: feedback já existe para decision %s", decision_id)
        return None

    fb = AIDecisionFeedback(
        decision_id=decision_id,
        feedback_type=feedback_type,
        operator_name=operator_name,
        operator_email=operator_email,
        actual_action_type=actual_action_type,
        actual_device_id=actual_device_id,
        actual_device_name=actual_device_name,
        actual_setpoint_to=actual_setpoint_to,
    )
    session.add(fb)
    return fb


# ── 3. Medir outcomes (job agendado) ─────────────────────────────────────────

def _compute_success_score(
    status_before: str | None,
    delta_15m: float | None,
    delta_30m: float | None,
    status_60m: str | None,
) -> float:
    score = 0.0
    # Zona que estava quente e voltou ao conforto = grande sucesso
    if status_before in ("WARM", "HOT", "CRITICAL") and status_60m == "COMFORT":
        score += 0.50
    # Temperatura caiu em 30min = bom sinal
    if delta_30m is not None and delta_30m < -0.5:
        score += 0.30
    # Reagiu rápido em 15min
    if delta_15m is not None and delta_15m < 0:
        score += 0.20
    return round(min(1.0, score), 3)


async def _get_zone_current_state(
    store_id: uuid.UUID,
    zone_key: str,
    session: AsyncSession,
) -> tuple[float | None, str | None]:
    """Retorna (avg_temp, thermal_status) atual da zona via digital twin."""
    try:
        from app.services.digital_twin import get_zone_twin
        twin = await get_zone_twin(store_id, zone_key, session)
        if twin:
            return twin.get("current_avg_temp"), twin.get("current_status")
    except Exception:
        pass
    return None, None


async def measure_outcomes() -> None:
    """Mede T+15, T+30, T+60 para decisões pendentes. Chamado a cada 5 min."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        # Busca outcomes incompletos de decisões com feedback (auto ou aprovado)
        result = await session.execute(
            select(AIDecisionOutcome, AIDecision)
            .join(AIDecision, AIDecisionOutcome.decision_id == AIDecision.id)
            .join(AIDecisionFeedback, AIDecisionFeedback.decision_id == AIDecision.id)
            .where(
                AIDecisionOutcome.completed == False,
                AIDecisionFeedback.feedback_type.in_(["auto_executed", "approved"]),
                AIDecision.created_at >= now - timedelta(hours=3),
                AIDecision.created_at <= now - timedelta(minutes=14),
            )
        )
        rows = result.all()

        if not rows:
            return

        for outcome, decision in rows:
            age_minutes = (now - decision.created_at).total_seconds() / 60
            current_temp, current_status = await _get_zone_current_state(
                decision.store_id, decision.zone_key, session
            )
            changed = False

            if outcome.measured_at_15 is None and age_minutes >= 15:
                outcome.temp_15m = current_temp
                outcome.status_15m = current_status
                outcome.delta_15m = (
                    round(current_temp - outcome.temp_before, 2)
                    if current_temp is not None and outcome.temp_before is not None
                    else None
                )
                outcome.measured_at_15 = now
                changed = True

            if outcome.measured_at_30 is None and age_minutes >= 30:
                outcome.temp_30m = current_temp
                outcome.status_30m = current_status
                outcome.delta_30m = (
                    round(current_temp - outcome.temp_before, 2)
                    if current_temp is not None and outcome.temp_before is not None
                    else None
                )
                outcome.measured_at_30 = now
                changed = True

            if outcome.measured_at_60 is None and age_minutes >= 60:
                outcome.temp_60m = current_temp
                outcome.status_60m = current_status
                outcome.delta_60m = (
                    round(current_temp - outcome.temp_before, 2)
                    if current_temp is not None and outcome.temp_before is not None
                    else None
                )
                outcome.measured_at_60 = now
                outcome.success_score = _compute_success_score(
                    outcome.status_before,
                    outcome.delta_15m,
                    outcome.delta_30m,
                    current_status,
                )
                outcome.completed = True
                changed = True

            if changed:
                session.add(outcome)

        await session.commit()

    # Atualiza learning scores após medir
    await update_learning_scores()


# ── 4. Agregar learning scores ────────────────────────────────────────────────

async def update_learning_scores() -> None:
    """Agrega outcomes completos em learning_scores por zona e device."""
    cutoff = datetime.utcnow() - timedelta(days=DECAY_DAYS)

    async with AsyncSessionLocal() as session:
        completed = await session.execute(
            select(AIDecisionOutcome, AIDecision, AIDecisionFeedback)
            .join(AIDecision, AIDecisionOutcome.decision_id == AIDecision.id)
            .join(AIDecisionFeedback, AIDecisionFeedback.decision_id == AIDecision.id)
            .where(
                AIDecisionOutcome.completed == True,
                AIDecisionOutcome.success_score.is_not(None),
                AIDecision.created_at >= cutoff,
            )
        )
        rows = completed.all()
        if not rows:
            return

        # Agrupa por (scope, scope_id, action_type, thermal_status)
        buckets: dict[tuple, list] = {}
        for outcome, decision, feedback in rows:
            if not decision.action_type or not decision.thermal_status:
                continue
            approved = feedback.feedback_type in ("auto_executed", "approved")
            for scope, scope_id in [
                ("zone", decision.zone_key),
                ("device", str(decision.device_id) if decision.device_id else None),
                ("store", str(decision.store_id)),
                ("global", "global"),
            ]:
                if scope_id is None:
                    continue
                key = (scope, scope_id, decision.action_type, decision.thermal_status)
                buckets.setdefault(key, []).append({
                    "approved": approved,
                    "success": outcome.success_score,
                    "delta_30m": outcome.delta_30m,
                    "age_days": (datetime.utcnow() - decision.created_at).days,
                })

        for (scope, scope_id, action_type, thermal_status), samples in buckets.items():
            n = len(samples)
            if n == 0:
                continue

            def weight(s):
                return max(0.3, 1.0 - s["age_days"] / DECAY_DAYS)

            total_w = sum(weight(s) for s in samples)
            approval_rate = sum(weight(s) for s in samples if s["approved"]) / total_w
            success_rate = sum(weight(s) * s["success"] for s in samples) / total_w
            deltas = [s["delta_30m"] for s in samples if s["delta_30m"] is not None]
            avg_delta = round(sum(deltas) / len(deltas), 3) if deltas else None
            confidence = min(1.0, n / 50)

            existing = await session.execute(
                select(AILearningScore).where(
                    AILearningScore.scope == scope,
                    AILearningScore.scope_id == scope_id,
                    AILearningScore.action_type == action_type,
                    AILearningScore.thermal_status == thermal_status,
                )
            )
            ls = existing.scalar_one_or_none()
            if ls is None:
                ls = AILearningScore(
                    scope=scope, scope_id=scope_id,
                    action_type=action_type, thermal_status=thermal_status,
                )
                session.add(ls)

            ls.approval_rate = round(approval_rate, 4)
            ls.success_rate = round(success_rate, 4)
            ls.avg_delta_30m = avg_delta
            ls.sample_count = n
            ls.confidence = round(confidence, 4)
            ls.updated_at = datetime.utcnow()

        await session.commit()
        logger.info("learning_scores atualizados: %d buckets", len(buckets))


# ── 5. Consultar bônus de aprendizado ────────────────────────────────────────

_score_cache: dict[tuple, tuple[float, datetime]] = {}
_CACHE_TTL = timedelta(minutes=10)


async def get_learning_bonus(
    *,
    zone_key: str,
    store_id: uuid.UUID,
    device_id: uuid.UUID | None,
    action_type: str,
    thermal_status: str,
    session: AsyncSession,
) -> float:
    """Retorna bônus de aprendizado (-12 a +12) para o candidato.

    Hierarquia: zona → device → store → global
    Aplica apenas quando sample_count >= MIN_SAMPLES.
    """
    cache_key = (zone_key, str(store_id), str(device_id), action_type, thermal_status)
    if cache_key in _score_cache:
        bonus, cached_at = _score_cache[cache_key]
        if datetime.utcnow() - cached_at < _CACHE_TTL:
            return bonus

    # Tenta escopos do mais específico ao mais geral
    scopes = [
        ("zone", zone_key),
        ("device", str(device_id) if device_id else None),
        ("store", str(store_id)),
        ("global", "global"),
    ]
    for scope, scope_id in scopes:
        if scope_id is None:
            continue
        result = await session.execute(
            select(AILearningScore).where(
                AILearningScore.scope == scope,
                AILearningScore.scope_id == scope_id,
                AILearningScore.action_type == action_type,
                AILearningScore.thermal_status == thermal_status,
            )
        )
        ls = result.scalar_one_or_none()
        if ls and ls.sample_count >= MIN_SAMPLES:
            # Bônus = sucesso e aprovação acima de 50% → positivo; abaixo → negativo
            success_factor = (ls.success_rate - 0.5) * 16.0   # -8 a +8
            approval_factor = (ls.approval_rate - 0.5) * 8.0  # -4 a +4
            raw = (success_factor + approval_factor) * ls.confidence
            bonus = round(max(MIN_BONUS, min(MAX_BONUS, raw)), 2)
            _score_cache[cache_key] = (bonus, datetime.utcnow())
            return bonus

    _score_cache[cache_key] = (0.0, datetime.utcnow())
    return 0.0


# ── 6. Stats para o dashboard ─────────────────────────────────────────────────

async def get_learning_stats(
    store_id: uuid.UUID | None,
    session: AsyncSession,
    days: int = 30,
) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=days)
    filters = [AIDecision.created_at >= cutoff]
    if store_id:
        filters.append(AIDecision.store_id == store_id)

    total_q = await session.execute(
        select(func.count()).select_from(AIDecision).where(*filters)
    )
    total = total_q.scalar() or 0

    fb_q = await session.execute(
        select(AIDecisionFeedback.feedback_type, func.count())
        .join(AIDecision, AIDecisionFeedback.decision_id == AIDecision.id)
        .where(*filters)
        .group_by(AIDecisionFeedback.feedback_type)
    )
    feedback_counts = {row[0]: row[1] for row in fb_q.all()}

    outcome_q = await session.execute(
        select(
            func.count().label("n"),
            func.avg(AIDecisionOutcome.success_score).label("avg_success"),
            func.avg(AIDecisionOutcome.delta_30m).label("avg_delta_30m"),
        )
        .join(AIDecision, AIDecisionOutcome.decision_id == AIDecision.id)
        .where(AIDecisionOutcome.completed == True, *filters)
    )
    outcome_row = outcome_q.one()

    approved = feedback_counts.get("approved", 0)
    rejected = feedback_counts.get("rejected", 0)
    auto = feedback_counts.get("auto_executed", 0)
    suggestions_total = approved + rejected + feedback_counts.get("modified", 0)

    return {
        "period_days": days,
        "total_decisions": total,
        "auto_executed": auto,
        "suggestions_total": suggestions_total,
        "approved": approved,
        "rejected": rejected,
        "modified": feedback_counts.get("modified", 0),
        "approval_rate": round(approved / suggestions_total, 3) if suggestions_total > 0 else None,
        "outcomes_measured": outcome_row.n or 0,
        "avg_success_score": round(float(outcome_row.avg_success), 3) if outcome_row.avg_success else None,
        "avg_delta_30m": round(float(outcome_row.avg_delta_30m), 2) if outcome_row.avg_delta_30m else None,
    }


async def get_zone_learning_context(
    zone_key: str,
    action_type: str,
    thermal_status: str,
    session: AsyncSession,
) -> dict | None:
    """Retorna contexto de aprendizado para exibir na sugestão ao operador."""
    result = await session.execute(
        select(AILearningScore).where(
            AILearningScore.scope == "zone",
            AILearningScore.scope_id == zone_key,
            AILearningScore.action_type == action_type,
            AILearningScore.thermal_status == thermal_status,
        )
    )
    ls = result.scalar_one_or_none()
    if not ls or ls.sample_count < MIN_SAMPLES:
        return None
    return {
        "sample_count": ls.sample_count,
        "approval_rate": ls.approval_rate,
        "success_rate": ls.success_rate,
        "avg_delta_30m": ls.avg_delta_30m,
        "confidence": ls.confidence,
        "explanation": (
            f"Ações similares nessa zona funcionaram {round(ls.success_rate * 100)}% "
            f"das vezes ({ls.sample_count} casos) e foram aprovadas pelos operadores "
            f"{round(ls.approval_rate * 100)}% das vezes."
        ),
    }
