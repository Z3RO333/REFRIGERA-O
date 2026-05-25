"""Análise espacial térmica para automação de zonas.

Funções puras (sem I/O, sem async) para detectar o hotspot térmico de uma zona
e calcular proximidade entre um device e esse hotspot.

Constante de conversão SVG: 14 px/m (igual ao frontend ThermalComfortMap.tsx).
"""
import math
from dataclasses import dataclass, field

# Variância mínima (°C) para considerar que existe hotspot localizado
HOTSPOT_VARIANCE_THRESHOLD = 1.5

# Devices com temperatura >= t_min + range * HOTSPOT_PERCENTILE são "quentes"
HOTSPOT_PERCENTILE = 0.65


@dataclass
class DevicePoint:
    """Snapshot de um aparelho com posição e temperatura para análise espacial."""
    device_id: str
    device_name: str
    pos_x: float | None
    pos_y: float | None
    influence_radius_m: float
    temperature: float | None
    is_on: bool
    is_off: bool
    is_available: bool
    btu: int


@dataclass
class Hotspot:
    """Subárea mais quente identificada dentro de uma zona."""
    x: float
    y: float
    peak_temp: float
    avg_hotspot_temp: float
    contributing_names: list[str] = field(default_factory=list)
    has_coordinates: bool = True


def detect_hotspot(devices: list[DevicePoint]) -> Hotspot | None:
    """Detecta hotspot térmico a partir das leituras dos devices.

    Retorna None se:
    - Menos de 2 devices com temperatura
    - Variância < HOTSPOT_VARIANCE_THRESHOLD (zona termicamente uniforme)

    O centro é o centroide dos devices mais quentes ponderado pelas temperaturas.
    """
    with_temp = [d for d in devices if d.temperature is not None]
    if len(with_temp) < 2:
        return None

    temps = [d.temperature for d in with_temp]
    t_min, t_max = min(temps), max(temps)
    if (t_max - t_min) < HOTSPOT_VARIANCE_THRESHOLD:
        return None

    threshold = t_min + (t_max - t_min) * HOTSPOT_PERCENTILE
    hot_devices = [d for d in with_temp if d.temperature >= threshold]
    if not hot_devices:
        return None

    peak_temp = max(d.temperature for d in hot_devices)
    avg_hotspot = sum(d.temperature for d in hot_devices) / len(hot_devices)
    names = [d.device_name for d in hot_devices]

    with_pos = [d for d in hot_devices if d.pos_x is not None and d.pos_y is not None]
    if not with_pos:
        return Hotspot(
            x=0.0, y=0.0,
            peak_temp=peak_temp,
            avg_hotspot_temp=round(avg_hotspot, 2),
            contributing_names=names,
            has_coordinates=False,
        )

    total_weight = sum(d.temperature for d in with_pos)
    cx = sum(d.pos_x * d.temperature for d in with_pos) / total_weight
    cy = sum(d.pos_y * d.temperature for d in with_pos) / total_weight

    return Hotspot(
        x=round(cx, 1),
        y=round(cy, 1),
        peak_temp=peak_temp,
        avg_hotspot_temp=round(avg_hotspot, 2),
        contributing_names=names,
        has_coordinates=True,
    )


def proximity_score(
    pos_x: float | None,
    pos_y: float | None,
    hotspot: Hotspot | None,
    influence_radius_m: float = 8.0,
) -> float:
    """Score de proximidade ao hotspot: 0.0 a 1.0.

    - 1.0 = no centro do hotspot
    - 0.5 = sem hotspot, sem coordenadas, ou hotspot sem posição (neutro)
    - Decai como e^(-dist / ref_radius)

    ref_radius = influence_radius_m * 14px/m (mínimo 50px).
    """
    if hotspot is None or not hotspot.has_coordinates:
        return 0.5
    if pos_x is None or pos_y is None:
        return 0.5

    M_TO_SVG = 14.0
    ref_radius = max(influence_radius_m * M_TO_SVG, 50.0)
    dist = math.sqrt((pos_x - hotspot.x) ** 2 + (pos_y - hotspot.y) ** 2)
    return round(math.exp(-dist / ref_radius), 4)
