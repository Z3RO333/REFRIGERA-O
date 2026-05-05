import uuid
from datetime import datetime
from app.rules.classifier import (
    STATUS_CRITICAL, STATUS_WARNING, STATUS_LOW_EFFICIENCY, STATUS_NO_READING,
    DELTA_P1_MIN
)

def generate_alert_if_needed(
    device_id: uuid.UUID,
    status: str,
    delta_temp: float | None,
    temperature: float | None,
    setpoint_cool: int | None,
    is_critical_environment: bool,
    last_reading_time: datetime | None,
) -> dict | None:
    """Returns alert dict or None if no alert should be generated"""
    alert_type = None
    severity = None
    message = None

    if status == STATUS_CRITICAL:
        alert_type = "TEMP_HIGH"
        if is_critical_environment and delta_temp and delta_temp > DELTA_P1_MIN:
            severity = "P1"
            message = f"CRÍTICO: Temperatura {temperature:.1f}°C (delta +{delta_temp:.1f}°C) em ambiente crítico"
        else:
            severity = "P2"
            message = f"CRÍTICO: Temperatura {temperature:.1f}°C (delta +{delta_temp:.1f}°C acima do setpoint {setpoint_cool}°C)"
    elif status == STATUS_NO_READING:
        alert_type = "NO_READING"
        severity = "P2"
        message = "Sem leitura: dispositivo pode estar offline ou sem comunicação"
    elif status == STATUS_LOW_EFFICIENCY:
        alert_type = "LOW_EFFICIENCY"
        severity = "P3"
        message = f"Baixa eficiência: equipamento ligado mas temperatura não reduz (delta +{delta_temp:.1f}°C)"
    elif status == "COMPRESSOR_CYCLING":
        alert_type = "PREVENTIVE_MAINTENANCE"
        severity = "P3"
        message = "Compressor ciclando: troca de estado excessiva detectada (possível defeito no compressor ou sensor)"
    elif status == STATUS_WARNING:
        alert_type = "TEMP_HIGH"
        severity = "P4"
        message = f"Atenção: Temperatura {temperature:.1f}°C acima do setpoint {setpoint_cool}°C"
    else:
        return None

    return {
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": severity,
        "status": "OPEN",
        "temperature_at_alert": temperature,
        "setpoint_at_alert": setpoint_cool,
        "delta_at_alert": delta_temp,
        "message": message,
        "opened_at": datetime.utcnow(),
    }
