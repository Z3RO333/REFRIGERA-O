from datetime import datetime, timedelta

# Limiares de horas de operação para indicar necessidade de manutenção
FILTER_HOURS    = 2_000   # troca de filtro
GENERAL_HOURS   = 5_000   # revisão geral
GAS_HOURS       = 8_000   # recarga de gás / compressor


def compute_maintenance_score(
    alerts_30d: list[dict],
    hours_in_warning_critical: float,
    hours_total_on: float,          # horas de operação acumuladas (lifetime)
    avg_efficiency_7d: float | None,
    hours_on_30d: float,
    last_maintenance: datetime | None,
) -> float:
    now = datetime.utcnow()
    alert_sum = sum(
        {"P1": 4, "P2": 3, "P3": 2, "P4": 1}.get(a.get("severity", "P4"), 1)
        for a in alerts_30d
    )
    weight_criticality = min(1.0, alert_sum / 40.0)
    weight_frequency = (hours_in_warning_critical / hours_total_on) if hours_total_on > 0 else 0.0
    weight_efficiency = 1.0 - (avg_efficiency_7d or 0.8)
    weight_usage = min(1.0, hours_on_30d / (24 * 30))
    if last_maintenance:
        days_since = (now - last_maintenance).days
    else:
        days_since = 180
    weight_maintenance = min(1.0, days_since / 180.0)

    # Bônus de desgaste por horas de operação acumuladas
    if hours_total_on >= GAS_HOURS:
        weight_wear = 1.0
    elif hours_total_on >= GENERAL_HOURS:
        weight_wear = 0.7
    elif hours_total_on >= FILTER_HOURS:
        weight_wear = 0.4
    else:
        weight_wear = 0.0

    score = (
        weight_criticality * 35
        + weight_frequency  * 20
        + weight_efficiency * 15
        + weight_usage      * 10
        + weight_maintenance * 5
        + weight_wear       * 15
    )
    return round(min(100.0, score), 2)


def maintenance_reasons(
    hours_total_on: float,
    last_maintenance: datetime | None,
    avg_efficiency: float | None,
    alerts_30d: list[dict],
) -> list[str]:
    reasons: list[str] = []
    now = datetime.utcnow()

    if hours_total_on >= GAS_HOURS:
        reasons.append(f"Recarga de gás/compressor — {int(hours_total_on):,}h de operação (lim. {GAS_HOURS:,}h)")
    elif hours_total_on >= GENERAL_HOURS:
        reasons.append(f"Revisão geral — {int(hours_total_on):,}h de operação (lim. {GENERAL_HOURS:,}h)")
    elif hours_total_on >= FILTER_HOURS:
        reasons.append(f"Troca de filtro — {int(hours_total_on):,}h de operação (lim. {FILTER_HOURS:,}h)")

    if not last_maintenance or (now - last_maintenance).days > 150:
        reasons.append("Manutenção preventiva vencida (>150 dias sem registro)")

    if avg_efficiency is not None and avg_efficiency < 0.6:
        reasons.append("Baixa eficiência energética detectada")

    p1p2 = [a for a in alerts_30d if a.get("severity") in ("P1", "P2")]
    if len(p1p2) >= 3:
        reasons.append(f"Múltiplos alertas críticos nos últimos 30 dias ({len(p1p2)})")

    return reasons
