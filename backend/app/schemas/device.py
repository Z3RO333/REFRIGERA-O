import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class DeviceStatusResponse(BaseModel):
    device_id: str
    brise_id: str
    name: str
    sector_name: str | None
    store_name: str | None
    status: str
    temperature: float | None
    humidity: int | None
    delta_temp: float | None
    efficiency_score: float | None
    state: bool | None
    setpoint_cool: int | None
    btu: int
    position_x: float | None
    position_y: float | None
    is_critical_environment: bool
    updated_at: str | None

    class Config:
        from_attributes = True

class DeviceParametersUpdate(BaseModel):
    mode_device: int
    mode_ac: int
    fan_speed: int
    setpoint_cool: int
    setpoint_heat: int
    eco_cool: int
    eco_heat: int

class DeviceControlCommand(BaseModel):
    action: Literal["power_on", "power_off", "temperature_up", "temperature_down"]
    step: int = Field(default=1, ge=1, le=5)

class DevicePositionUpdate(BaseModel):
    position_x: float | None
    position_y: float | None

class DeviceMetadataUpdate(BaseModel):
    btu: int = Field(ge=1000, le=300000)


class DeviceCreate(BaseModel):
    brise_device_id: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    sector_id: uuid.UUID | None = None
    btu: int = Field(default=12000, ge=1000, le=300000)
    enable_fan: bool = True
    enable_heat: bool = False
    dnd: bool = False
    time_zone: int = Field(default=-4, ge=-12, le=14)
    group_level1: str | None = Field(default=None, max_length=50)
    group_level2: str | None = Field(default=None, max_length=50)
    group_level3: str | None = Field(default=None, max_length=50)
    group_level4: str | None = Field(default=None, max_length=50)
    position_x: float | None = None
    position_y: float | None = None
    polling_interval: int = Field(default=300, ge=60, le=86400)
    is_critical_environment: bool = False
    active: bool = True
    last_maintenance: datetime | None = None
    influence_radius_m: int = Field(default=8, ge=1, le=100)


class ExternalSensorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source_url: str = Field(min_length=1, max_length=500)
    sector_id: uuid.UUID | None = None
    setpoint_cool: int = Field(default=24, ge=16, le=30)
    is_critical: bool = False
    influence_radius_m: int = Field(default=8, ge=1, le=100)
