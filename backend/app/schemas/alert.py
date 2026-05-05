import uuid
from datetime import datetime
from pydantic import BaseModel

class AlertResponse(BaseModel):
    id: str
    device_id: str
    device_name: str | None
    store_name: str | None
    sector_name: str | None
    alert_type: str
    severity: str
    status: str
    temperature_at_alert: float | None
    setpoint_at_alert: int | None
    delta_at_alert: float | None
    message: str | None
    opened_at: datetime
    acked_at: datetime | None
    acked_by: str | None
    resolved_at: datetime | None

    class Config:
        from_attributes = True

class AlertAck(BaseModel):
    notes: str | None = None
