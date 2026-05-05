from pydantic import BaseModel

class KPISummary(BaseModel):
    total_devices: int
    devices_normal: int
    devices_warning: int
    devices_critical: int
    devices_no_reading: int
    devices_low_efficiency: int
    devices_off: int
    devices_online: int
    alerts_p1_open: int
    alerts_p2_open: int
    avg_temperature: float | None
    avg_efficiency_score: float | None
    compliance_rate: float | None

class StoreKPI(BaseModel):
    store_id: str
    store_name: str
    total_devices: int
    devices_normal: int
    devices_warning: int
    devices_critical: int
    devices_no_reading: int
    devices_low_efficiency: int
    compliance_rate: float | None
