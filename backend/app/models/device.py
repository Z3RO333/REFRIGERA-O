import uuid
from datetime import datetime
from sqlalchemy import BigInteger, String, Boolean, DateTime, Float, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base

class Device(Base):
    __tablename__ = "devices"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brise_device_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    sector_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("store_sectors.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    btu: Mapped[int] = mapped_column(Integer, default=12000)
    enable_fan: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_heat: Mapped[bool] = mapped_column(Boolean, default=False)
    dnd: Mapped[bool] = mapped_column(Boolean, default=False)
    time_zone: Mapped[int] = mapped_column(Integer, default=-4)
    group_level1: Mapped[str | None] = mapped_column(String(50))
    group_level2: Mapped[str | None] = mapped_column(String(50))
    group_level3: Mapped[str | None] = mapped_column(String(50))
    group_level4: Mapped[str | None] = mapped_column(String(50))
    position_x: Mapped[float | None] = mapped_column(Float)
    position_y: Mapped[float | None] = mapped_column(Float)
    polling_interval: Mapped[int] = mapped_column(Integer, default=300)
    is_critical_environment: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_maintenance: Mapped[datetime | None] = mapped_column(DateTime)
    source_url: Mapped[str | None] = mapped_column(Text)          # sensor externo HTTP (NULL = Brise)
    influence_radius_m: Mapped[int] = mapped_column(Integer, default=8)  # raio de influência no mapa térmico (metros)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sector: Mapped["StoreSector"] = relationship("StoreSector", back_populates="devices")
    parameters: Mapped["DeviceParameters"] = relationship("DeviceParameters", back_populates="device", uselist=False)
    status_latest: Mapped["DeviceStatusLatest"] = relationship("DeviceStatusLatest", back_populates="device", uselist=False)

class DeviceParameters(Base):
    __tablename__ = "device_parameters"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), unique=True)
    mode_device: Mapped[int] = mapped_column(Integer, default=0)
    mode_ac: Mapped[int] = mapped_column(Integer, default=0)
    fan_speed: Mapped[int] = mapped_column(Integer, default=2)
    setpoint_cool: Mapped[int] = mapped_column(Integer, default=24)
    setpoint_heat: Mapped[int] = mapped_column(Integer, default=20)
    eco_cool: Mapped[int] = mapped_column(Integer, default=22)
    eco_heat: Mapped[int] = mapped_column(Integer, default=18)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    device: Mapped["Device"] = relationship("Device", back_populates="parameters")

class DeviceStatusLatest(Base):
    __tablename__ = "device_status_latest"
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True)
    state: Mapped[bool | None] = mapped_column(Boolean)
    temperature: Mapped[float | None] = mapped_column(Float)
    humidity: Mapped[float | None] = mapped_column(Float)
    consumption: Mapped[float | None] = mapped_column(Float)
    consumption_estimated: Mapped[float | None] = mapped_column(Float)
    status_classification: Mapped[str | None] = mapped_column(String(30))
    delta_temp: Mapped[float | None] = mapped_column(Float)
    efficiency_score: Mapped[float | None] = mapped_column(Float)
    consecutive_readings_count: Mapped[int] = mapped_column(Integer, default=0)
    accumulated_on_minutes: Mapped[int | None] = mapped_column(BigInteger)
    accumulated_off_minutes: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    device: Mapped["Device"] = relationship("Device", back_populates="status_latest")
