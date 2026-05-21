from pydantic import BaseModel, Field


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=20)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=2)
    timezone: int = Field(default=-4, ge=-12, le=14)
    latitude: float | None = None
    longitude: float | None = None
    active: bool = True


class SectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    floor: int = Field(default=1, ge=-10, le=100)
    area_m2: float | None = Field(default=None, ge=0)
    floor_plan_url: str | None = None
    is_critical: bool = False


class FloorPlanUpdate(BaseModel):
    floor_plan_url: str | None = None
