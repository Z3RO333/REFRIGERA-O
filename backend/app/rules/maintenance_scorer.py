from datetime import datetime, timedelta

def compute_maintenance_score(
    alerts_30d: list[dict],
    hours_in_warning_critical: float,
    hours_total_on: float,
    avg_efficiency_7d: float | None,
    hours_on_30d: float,
    last_maintenance: datetime | None,
) -> float:
    now = datetime.utcnow()
    alert_sum = sum(
        {"P1": 4, "P2": 3, "P3": 2, "P4": 1}.get(a.get("severity", "P4"), 1)
        for a in alerts_30d
    )
    max_alert_sum = max(alert_sum, 1)
    weight_criticality = min(1.0, alert_sum / 40.0)
    weight_frequency = (hours_in_warning_critical / hours_total_on) if hours_total_on > 0 else 0.0
    weight_efficiency = 1.0 - (avg_efficiency_7d or 0.8)
    weight_usage = min(1.0, hours_on_30d / (24 * 30))
    if last_maintenance:
        days_since = (now - last_maintenance).days
    else:
        days_since = 180
    weight_maintenance = min(1.0, days_since / 180.0)
    score = (
        weight_criticality * 40
        + weight_frequency * 25
        + weight_efficiency * 20
        + weight_usage * 10
        + weight_maintenance * 5
    )
    return round(min(100.0, score), 2)
