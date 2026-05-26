from datetime import datetime, timedelta

STATUS_NORMAL = "NORMAL"
STATUS_WARNING = "ATENÇÃO"
STATUS_CRITICAL = "CRÍTICO"
STATUS_LOW_EFFICIENCY = "BAIXA_EFICIÊNCIA"
STATUS_NO_READING = "SEM_LEITURA"
STATUS_STALE_READING = "LEITURA_STALE"
STATUS_OFF = "DESLIGADO"

DELTA_WARNING_MIN = 2.0
DELTA_CRITICAL_MIN = 6.0
DELTA_P1_MIN = 8.0
CONSECUTIVE_READINGS_REQUIRED = 3
LOW_EFFICIENCY_READINGS_REQUIRED = 6
NO_READING_THRESHOLD_MINUTES = 15

# Limites da classificação por zona (°C acima do ideal_max)
_ZONE_WARM_DELTA     = 1.5   # ATENÇÃO: até +1.5°C acima do ideal_max
_ZONE_HOT_DELTA      = 3.5   # ATENÇÃO severa: até +3.5°C (ainda STATUS_WARNING)
# acima de _ZONE_HOT_DELTA → STATUS_CRITICAL


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
    zone_ideal_min: float | None = None,
    zone_ideal_max: float | None = None,
) -> tuple[str, float | None, float | None]:
    """
    Retorna (status, delta_temp, efficiency_score).

    Quando zone_ideal_min/max são fornecidos, a classificação de conforto
    usa a faixa ideal da zona em vez de depender apenas do delta do setpoint.
    O delta_temp retornado continua sendo temp - setpoint_cool (usado pela IA
    e cálculo de eficiência); o STATUS reflete o conforto real do ambiente.
    """
    now = datetime.utcnow()
    if last_reading_time and (now - last_reading_time) > timedelta(minutes=NO_READING_THRESHOLD_MINUTES):
        return STATUS_NO_READING, None, None
    if state is False:
        return STATUS_OFF, None, None
    if temperature is None:
        return STATUS_NO_READING, None, None
    if mode_ac not in (0, 2):
        return STATUS_NORMAL, None, None

    if current_status in (STATUS_NO_READING, STATUS_OFF):
        current_status = None
        consecutive_count = CONSECUTIVE_READINGS_REQUIRED

    delta = compute_delta_temp(temperature, setpoint_cool)
    efficiency = compute_efficiency_score(delta)

    # ── Detecção de BAIXA_EFICIÊNCIA ──────────────────────────────────────────
    # Independe do tipo de classificação (setpoint ou zona): se o compressor
    # está trabalhando abaixo do mínimo com ambiente quente, é falha de capacidade.
    if delta > 1.0:
        btu_threshold = compute_btu_threshold(btu)
        if (
            consumption_estimated is not None
            and consumption_estimated < btu_threshold
            and consecutive_count >= LOW_EFFICIENCY_READINGS_REQUIRED
        ):
            return STATUS_LOW_EFFICIENCY, delta, efficiency

    # ── Classificação por faixa de conforto da zona ───────────────────────────
    if zone_ideal_min is not None and zone_ideal_max is not None:
        zone_excess = temperature - zone_ideal_max  # positivo = acima do conforto

        if zone_excess > _ZONE_HOT_DELTA:
            if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
                return STATUS_CRITICAL, delta, efficiency
            return current_status or STATUS_WARNING, delta, efficiency

        if zone_excess > _ZONE_WARM_DELTA:
            if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
                return STATUS_WARNING, delta, efficiency
            return current_status or STATUS_NORMAL, delta, efficiency

        if temperature < zone_ideal_min:
            # Ambiente abaixo do conforto: NORMAL (frio não é risco operacional)
            return STATUS_NORMAL, delta, efficiency

        # Dentro da faixa de conforto → NORMAL
        return STATUS_NORMAL, delta, efficiency

    # ── Classificação legada por delta do setpoint ────────────────────────────
    if delta > DELTA_CRITICAL_MIN:
        if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
            return STATUS_CRITICAL, delta, efficiency
        return current_status or STATUS_WARNING, delta, efficiency
    if delta > DELTA_WARNING_MIN:
        if consecutive_count >= CONSECUTIVE_READINGS_REQUIRED:
            return STATUS_WARNING, delta, efficiency
        return current_status or STATUS_NORMAL, delta, efficiency
    return STATUS_NORMAL, delta, efficiency
