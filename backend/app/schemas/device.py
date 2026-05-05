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
    position_x: float
    position_y: float

class DeviceMetadataUpdate(BaseModel):
    btu: int = Field(ge=1000, le=300000)
