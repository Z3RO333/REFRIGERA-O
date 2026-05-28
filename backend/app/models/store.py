import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Float, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base

class Store(Base):
    __tablename__ = "stores"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[int] = mapped_column(default=-4)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # ── Horário de funcionamento (horário local Manaus, UTC-4) ────────────────
    # close_next_day=True quando a loja fecha após a meia-noite (ex: Flores 01h, Boulevard 00h)
    open_hour: Mapped[int] = mapped_column(Integer, default=7)
    open_minute: Mapped[int] = mapped_column(Integer, default=0)
    close_hour: Mapped[int] = mapped_column(Integer, default=18)
    close_minute: Mapped[int] = mapped_column(Integer, default=0)
    close_next_day: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sectors: Mapped[list["StoreSector"]] = relationship("StoreSector", back_populates="store")

class StoreSector(Base):
    __tablename__ = "store_sectors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stores.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100))
    floor: Mapped[int] = mapped_column(default=1)
    area_m2: Mapped[float | None] = mapped_column(Float)
    floor_plan_url: Mapped[str | None] = mapped_column(Text)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    store: Mapped["Store"] = relationship("Store", back_populates="sectors")
    devices: Mapped[list["Device"]] = relationship("Device", back_populates="sector")
