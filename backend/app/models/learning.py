import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Boolean, DateTime, Float, Integer,
    ForeignKey, Text, SmallInteger,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.session import Base


class AIDecision(Base):
    """Contexto completo de cada decisão da IA (sugestão ou ação automática).

    Vinculada 1-para-1 ao ZoneAction correspondente. Armazena o snapshot do
    estado da zona no momento da decisão para permitir cálculo de outcome.
    """
    __tablename__ = "ai_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zone_actions.id", ondelete="SET NULL"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False, index=True)
    zone_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    zone_label: Mapped[str | None] = mapped_column(String(100))

    # Tipo da decisão
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 'auto' | 'suggestion' | 'blocked'

    # Snapshot do estado da zona
    thermal_status: Mapped[str | None] = mapped_column(String(20))   # WARM/HOT/CRITICAL/COMFORT
    avg_temp: Mapped[float | None] = mapped_column(Float)
    ideal_min: Mapped[float | None] = mapped_column(Float)
    ideal_max: Mapped[float | None] = mapped_column(Float)
    trend_c_per_hour: Mapped[float | None] = mapped_column(Float)
    freshness_ratio: Mapped[float | None] = mapped_column(Float)
    devices_on: Mapped[int | None] = mapped_column(SmallInteger)
    devices_off: Mapped[int | None] = mapped_column(SmallInteger)
    had_hotspot: Mapped[bool] = mapped_column(Boolean, default=False)
    hotspot_peak_temp: Mapped[float | None] = mapped_column(Float)

    # Ação sugerida/executada
    action_type: Mapped[str | None] = mapped_column(String(30))
    # 'setpoint_down' | 'setpoint_up' | 'power_on' | 'wait' | 'fan_up'
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"))
    device_name: Mapped[str | None] = mapped_column(String(100))
    setpoint_from: Mapped[int | None] = mapped_column(SmallInteger)
    setpoint_to: Mapped[int | None] = mapped_column(SmallInteger)
    fan_speed_from: Mapped[int | None] = mapped_column(SmallInteger)
    fan_speed_to: Mapped[int | None] = mapped_column(SmallInteger)

    # Metadados da decisão
    confidence: Mapped[float | None] = mapped_column(Float)
    energy_strategy: Mapped[str | None] = mapped_column(String(30))
    thermal_impact_score: Mapped[float | None] = mapped_column(Float)
    energy_cost_score: Mapped[float | None] = mapped_column(Float)
    final_score: Mapped[float | None] = mapped_column(Float)
    learning_bonus_applied: Mapped[float | None] = mapped_column(Float)  # bônus de aprendizado usado
    was_in_recovery: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AIDecisionFeedback(Base):
    """Feedback do operador sobre uma decisão da IA."""
    __tablename__ = "ai_decision_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_decisions.id", ondelete="CASCADE"),
        nullable=False, index=True, unique=True,
    )

    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 'auto_executed' | 'approved' | 'rejected' | 'modified'

    operator_name: Mapped[str | None] = mapped_column(String(100))
    operator_email: Mapped[str | None] = mapped_column(String(200))

    # Se o operador modificou a sugestão
    actual_action_type: Mapped[str | None] = mapped_column(String(30))
    actual_device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actual_device_name: Mapped[str | None] = mapped_column(String(100))
    actual_setpoint_to: Mapped[int | None] = mapped_column(SmallInteger)

    feedback_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AIDecisionOutcome(Base):
    """Resultado medido da decisão nos intervalos T+15, T+30, T+60 minutos."""
    __tablename__ = "ai_decision_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_decisions.id", ondelete="CASCADE"),
        nullable=False, index=True, unique=True,
    )

    temp_before: Mapped[float | None] = mapped_column(Float)
    status_before: Mapped[str | None] = mapped_column(String(20))

    # T+15 minutos
    temp_15m: Mapped[float | None] = mapped_column(Float)
    status_15m: Mapped[str | None] = mapped_column(String(20))
    delta_15m: Mapped[float | None] = mapped_column(Float)
    measured_at_15: Mapped[datetime | None] = mapped_column(DateTime)

    # T+30 minutos
    temp_30m: Mapped[float | None] = mapped_column(Float)
    status_30m: Mapped[str | None] = mapped_column(String(20))
    delta_30m: Mapped[float | None] = mapped_column(Float)
    measured_at_30: Mapped[datetime | None] = mapped_column(DateTime)

    # T+60 minutos
    temp_60m: Mapped[float | None] = mapped_column(Float)
    status_60m: Mapped[str | None] = mapped_column(String(20))
    delta_60m: Mapped[float | None] = mapped_column(Float)
    measured_at_60: Mapped[datetime | None] = mapped_column(DateTime)

    # Score de sucesso calculado (0.0–1.0)
    success_score: Mapped[float | None] = mapped_column(Float)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)  # True quando T+60 medido


class AILearningScore(Base):
    """Score de aprendizado agregado por contexto (zona/device/store/global).

    Atualizado periodicamente a partir dos outcomes registrados.
    Usado pelo zone_controller para aplicar bônus/penalidade no ranking de candidatos.
    """
    __tablename__ = "ai_learning_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    scope: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # 'zone' | 'device' | 'store' | 'global'
    scope_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # zone_key, device_id (str), store_id (str), ou 'global'

    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    thermal_status: Mapped[str] = mapped_column(String(20), nullable=False)

    approval_rate: Mapped[float] = mapped_column(Float, default=0.5)
    success_rate: Mapped[float] = mapped_column(Float, default=0.5)
    avg_delta_30m: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
