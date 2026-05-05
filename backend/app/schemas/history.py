from datetime import datetime
from pydantic import BaseModel

class HistoryPoint(BaseModel):
    time: datetime
    temperature: float | None
    humidity: int | None
    status_classification: str | None
    delta_temp: float | None
    efficiency_score: float | None
    state: bool | None
    consumption_estimated: float | None

class HistoryStats(BaseModel):
    avg_temp: float | None
    max_temp: float | None
    min_temp: float | None
    avg_efficiency: float | None
    hours_critical: float
    hours_warning: float
    hours_normal: float
    total_kwh: float | None
