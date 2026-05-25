import uuid
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Float, Integer, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


class ZoneAutomation(Base):
    """Configuração de automação por zona (uma linha por loja+zona)."""
    __tablename__ = "zone_automations"
    __table_args__ = (UniqueConstraint("store_id", "zone_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    zone_key: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="manual")
    # manual | suggestion | semi | auto
    setpoint_min: Mapped[int] = mapped_column(Integer, default=18)
    setpoint_max: Mapped[int] = mapped_column(Integer, default=28)
    max_daily_adjustments: Mapped[int] = mapped_column(Integer, default=6)

    # ── Guardrails ────────────────────────────────────────────────────────────
    allowed_start_hour: Mapped[int] = mapped_column(Integer, default=7)
    allowed_start_minute: Mapped[int] = mapped_column(Integer, default=0)   # 07:00
    allowed_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    allowed_end_minute: Mapped[int] = mapped_column(Integer, default=0)     # 18:00
    is_critical_zone: Mapped[bool] = mapped_column(Boolean, default=False)  # bloqueia auto/semi

    # ── Prioridade operacional ────────────────────────────────────────────────
    # conforto | economia | estabilidade | manutencao
    priority: Mapped[str] = mapped_column(String(20), default="conforto")

    # ── Tipo de zona e bloqueio térmico ──────────────────────────────────────
    zone_type: Mapped[str] = mapped_column(String(20), default="ABERTA")
    reading_confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # ── Manutenção / bloqueio manual ─────────────────────────────────────────
    # mode == "maintenance" → automação completamente suspensa até liberação explícita
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime)
    blocked_by_user_name: Mapped[str | None] = mapped_column(String(100))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ZoneAction(Base):
    """Registro auditável de cada decisão do controlador de zona."""
    __tablename__ = "zone_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    zone_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    zone_label: Mapped[str | None] = mapped_column(String(100))

    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"))
    device_name: Mapped[str | None] = mapped_column(String(100))

    direction: Mapped[str | None] = mapped_column(String(10))     # up | down | none
    temp_before: Mapped[float | None] = mapped_column(Float)
    temp_after: Mapped[float | None] = mapped_column(Float)
    ideal_min: Mapped[float] = mapped_column(Float, default=22)
    ideal_max: Mapped[float] = mapped_column(Float, default=24)
    setpoint_before: Mapped[int | None] = mapped_column(Integer)
    setpoint_after: Mapped[int | None] = mapped_column(Integer)

    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)        # 0.0 – 1.0
    mode: Mapped[str | None] = mapped_column(String(20))

    # suggestion | pending_verification | executed | blocked | verified_success | verified_failure
    status: Mapped[str] = mapped_column(String(30), default="suggestion", index=True)
    block_reason: Mapped[str | None] = mapped_column(Text)

    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Métricas de latência (ms)
    decision_ms: Mapped[int | None] = mapped_column(Integer)   # tempo total da decisão
    api_ms:      Mapped[int | None] = mapped_column(Integer)   # tempo da chamada à Brise API
