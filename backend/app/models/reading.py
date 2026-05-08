import uuid
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.session import Base

class DeviceReading(Base):
    __tablename__ = "device_readings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), index=True)
    state: Mapped[bool | None] = mapped_column(Boolean)
    temperature: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    consumption: Mapped[float | None] = mapped_column(Float)
    consumption_estimated: Mapped[float | None] = mapped_column(Float)
    status_classification: Mapped[str | None] = mapped_column(String(30))
    delta_temp: Mapped[float | None] = mapped_column(Float)
    efficiency_score: Mapped[float | None] = mapped_column(Float)
    accumulated_on_minutes: Mapped[int | None] = mapped_column(BigInteger)
    accumulated_off_minutes: Mapped[int | None] = mapped_column(BigInteger)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
