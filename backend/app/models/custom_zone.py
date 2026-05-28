import uuid
from datetime import datetime
from sqlalchemy import Boolean, String, DateTime, Float, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.session import Base


class CustomZone(Base):
    __tablename__ = "custom_zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    zone_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(20), default="ABERTA")
    ideal_min: Mapped[int] = mapped_column(Integer, default=20)
    ideal_max: Mapped[int] = mapped_column(Integer, default=24)
    # Geometria em % da planta — independente de resolução/tamanho de tela
    # {"type":"polygon","points":[{"x":12.4,"y":18.2},...],"unit":"percent"}
    geometry: Mapped[dict | None] = mapped_column(JSONB)
    floor: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(default=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(100))
    created_by_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CustomZoneDevice(Base):
    __tablename__ = "custom_zone_devices"

    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_zones.id", ondelete="CASCADE"), primary_key=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    # Unicidade de binding activo — índice parcial WHERE active = true
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Ciclo de vida do binding
    binding_mode: Mapped[str] = mapped_column(String(30), default="spatial_auto", nullable=False)
    # True quando o device está posicionado fora do polígono da zona
    out_of_shape: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
