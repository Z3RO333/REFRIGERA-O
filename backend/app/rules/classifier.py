from datetime import datetime, timedelta

STATUS_NORMAL = "NORMAL"
STATUS_WARNING = "ATENÇÃO"
STATUS_CRITICAL = "CRÍTICO"
STATUS_LOW_EFFICIENCY = "BAIXA_EFICIÊNCIA"
STATUS_NO_READING = "SEM_LEITURA"
STATUS_OFF = "DESLIGADO"

DELTA_WARNING_MIN = 2.0
DELTA_CRITICAL_MIN = 6.0
DELTA_P1_MIN = 8.0
CONSECUTIVE_READINGS_REQUIRED = 3
LOW_EFFICIENCY_READINGS_REQUIRED = 6
NO_READING_THRESHOLD_MINUTES = 15

def compute_delta_temp(temperature: float, setpoint_cool: int) -> float:
    return temperature - setpoint_cool

def compute_efficiency_score(delta_temp: float, max_delta: float = 8.0) -> float:
    return max(0.0, 1.0 - (delta_temp / max_delta))

def compute_btu_threshold(btu_nominal: int) -> float:
    return (btu_nominal * 0.30) / 3412.0

def classify_status(
    state: bool | None,
    temperature: float | None,
    setpoint_cool: int,
    mode_ac: int,
    btu: int,
    consumption_estimated: float | None,
    last_reading_time: datetime | None,
    consecutive_count: int,
    current_status: str | None,
) -> tuple[str, float | None, float | None]:
    """Returns (status, delta_temp, efficiency_score)"""
    now = datetime.utcnow()
    if last_reading_time and (now - last_reading_time) > timedelta(minutes=NO_READING_THRESHOLD_MINUTES):
        return STATUS_NO_READING, None, None
    if state is False:
        return STATUS_OFF, None, None
    if temperature is None:
        return STATUS_NO_READING, None, None
    if mode_ac not in (0, 2):
        return STATUS_NORMAL, None, 1.0

    if current_status in (STATUS_NO_READING, STATUS_OFF):
        current_status = None
        consecutive_count = CONSECUTIVE_READINGS_REQUIRED

    delta = compute_delta_temp(temperature, setpoint_cool)
    efficiency = compute_efficiency_score(delta)
    if delta > DELTA_CRITICAL_MIN:
        if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
            return STATUS_CRITICAL, delta, efficiency
        return current_status or STATUS_WARNING, delta, efficiency
    if delta > DELTA_WARNING_MIN:
        if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
            return STATUS_WARNING, delta, efficiency
        return current_status or STATUS_NORMAL, delta, efficiency
    if DELTA_WARNING_MIN >= delta > 1.0:
        btu_threshold = compute_btu_threshold(btu)
        below_consumption = (consumption_estimated is not None and consumption_estimated < btu_threshold)
        low_eff = efficiency < 0.5
        if below_consumption and low_eff and consecutive_count >= LOW_EFFICIENCY_READINGS_REQUIRED:
            return STATUS_LOW_EFFICIENCY, delta, efficiency
    return STATUS_NORMAL, delta, efficiency
