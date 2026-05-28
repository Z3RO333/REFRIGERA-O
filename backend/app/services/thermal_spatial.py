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

# Distância máxima para considerar dois pontos quentes como o mesmo bolsão.
# Evita que dois cantos quentes sejam fundidos em um centroide artificial no meio.
HOTSPOT_CLUSTER_MIN_RADIUS_PX = 90.0


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
    peak_device_name: str = ""  # device com a maior temperatura no cluster


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

    selected_hot_devices = _select_hotspot_cluster(hot_devices)

    peak_device = max(selected_hot_devices, key=lambda d: d.temperature)
    peak_temp = peak_device.temperature
    avg_hotspot = sum(d.temperature for d in selected_hot_devices) / len(selected_hot_devices)
    names = [d.device_name for d in selected_hot_devices]

    with_pos = [d for d in selected_hot_devices if d.pos_x is not None and d.pos_y is not None]
    if not with_pos:
        return Hotspot(
            x=0.0, y=0.0,
            peak_temp=peak_temp,
            avg_hotspot_temp=round(avg_hotspot, 2),
            contributing_names=names,
            has_coordinates=False,
            peak_device_name=peak_device.device_name,
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
        peak_device_name=peak_device.device_name,
    )


def _distance(a: DevicePoint, b: DevicePoint) -> float | None:
    if a.pos_x is None or a.pos_y is None or b.pos_x is None or b.pos_y is None:
        return None
    return math.sqrt((a.pos_x - b.pos_x) ** 2 + (a.pos_y - b.pos_y) ** 2)


def _cluster_radius(device: DevicePoint) -> float:
    return max(float(device.influence_radius_m or 8.0) * 14.0, HOTSPOT_CLUSTER_MIN_RADIUS_PX)


def _select_hotspot_cluster(hot_devices: list[DevicePoint]) -> list[DevicePoint]:
    """Escolhe o bolsão quente mais relevante.

    Antes o hotspot usava o centroide de todos os pontos quentes. Em lojas com
    dois cantos quentes, isso criava um ponto médio falso e podia selecionar um
    AC distante do canto realmente mais quente.
    """
    positioned = [d for d in hot_devices if d.pos_x is not None and d.pos_y is not None]
    if len(positioned) <= 1:
        return hot_devices

    clusters: list[list[DevicePoint]] = []
    remaining = positioned[:]
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            for candidate in remaining[:]:
                if any(
                    (dist := _distance(candidate, member)) is not None
                    and dist <= max(_cluster_radius(candidate), _cluster_radius(member))
                    for member in cluster
                ):
                    cluster.append(candidate)
                    remaining.remove(candidate)
                    changed = True
        clusters.append(cluster)

    def rank(cluster: list[DevicePoint]) -> tuple[float, float, int]:
        temps = [float(d.temperature or 0.0) for d in cluster]
        return (max(temps), sum(temps) / len(temps), len(cluster))

    return max(clusters, key=rank)


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
