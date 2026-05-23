import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ZoneMode = Literal["manual", "suggestion", "semi", "auto", "maintenance"]
ZonePriority = Literal["conforto", "economia", "estabilidade", "manutencao"]
ZoneType = Literal["ABERTA", "SALA_FECHADA"]


class ZoneModeUpdate(BaseModel):
    mode: ZoneMode = "manual"
    priority: ZonePriority | None = None
    blocked_reason: str | None = Field(default=None, max_length=500)
    blocked_until: datetime | None = None
    setpoint_min: int | None = Field(default=None, ge=16, le=30)
    setpoint_max: int | None = Field(default=None, ge=16, le=30)
    max_daily_adjustments: int | None = Field(default=None, ge=0, le=50)

    @model_validator(mode="after")
    def validate_setpoint_range(self):
        if self.setpoint_min is not None and self.setpoint_max is not None:
            if self.setpoint_min >= self.setpoint_max:
                raise ValueError("setpoint_min deve ser menor que setpoint_max")
        return self


class ZoneGuardrailsUpdate(BaseModel):
    allowed_start_time: str | None = None
    allowed_end_time: str | None = None
    is_critical_zone: bool | None = None


class CustomZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ideal_min: int = Field(default=20, ge=16, le=30)
    ideal_max: int = Field(default=24, ge=16, le=30)
    zone_type: ZoneType = "ABERTA"
    device_ids: list[uuid.UUID] = Field(default_factory=list)
    mode: ZoneMode = "manual"
    # Geometria canônica em % da planta — independente de resolução
    # {"type":"polygon","points":[{"x":12.4,"y":18.2},...],"unit":"percent"}
    geometry: dict[str, Any] | None = None
    floor: int = 1
    color: str | None = None

    @model_validator(mode="after")
    def validate_temp_range(self):
        if self.ideal_min >= self.ideal_max:
            raise ValueError("ideal_min deve ser menor que ideal_max")
        return self


class CustomZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    ideal_min: int | None = Field(default=None, ge=16, le=30)
    ideal_max: int | None = Field(default=None, ge=16, le=30)
    zone_type: ZoneType | None = None
    device_ids: list[uuid.UUID] | None = None
    geometry: dict[str, Any] | None = None
    floor: int | None = None
    color: str | None = None

    @model_validator(mode="after")
    def validate_temp_range(self):
        if self.ideal_min is not None and self.ideal_max is not None:
            if self.ideal_min >= self.ideal_max:
                raise ValueError("ideal_min deve ser menor que ideal_max")
        return self
