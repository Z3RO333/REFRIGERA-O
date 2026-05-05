import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Float, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    temperature_at_alert: Mapped[float | None] = mapped_column(Float)
    setpoint_at_alert: Mapped[int | None] = mapped_column(Integer)
    delta_at_alert: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime)
    acked_by: Mapped[str | None] = mapped_column(String(100))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    device: Mapped["Device"] = relationship("Device")
