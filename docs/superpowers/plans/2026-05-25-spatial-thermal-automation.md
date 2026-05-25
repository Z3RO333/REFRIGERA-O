# Automação Térmica Espacial — Priorização por Hotspot


> **Status atual (2026-05-25):** implementação aplicada. O backend usa hotspot para priorizar power-on e setpoint quando a zona está fora da faixa. Também foi adicionada regra de hotspot local: se a média da zona estiver verde, mas uma subárea passar do `ideal_max`, o controlador não reduz setpoint da zona inteira; ele prioriza ligar aparelho desligado, comunicando e controlável próximo ao hotspot, ou registra sugestão operacional se não houver aparelho seguro.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O controlador de zonas detecta a subárea mais quente ("hotspot") dentro da zona e prioriza ligar aparelhos desligados próximos ao hotspot, em vez de selecionar sempre pelo maior BTU ou maior delta_temp.

**Architecture:** Novo módulo puro `thermal_spatial.py` (zero I/O, totalmente testável) com `DevicePoint`, `Hotspot`, `detect_hotspot()` e `proximity_score()`. O `zone_controller.py` recebe parâmetro `hotspot` nas funções de seleção e o computa em `_evaluate_zone()` a partir das leituras reais dos devices antes de qualquer seleção. A decisão usa dois níveis: média global da zona (já existente) + hotspot local (novo).

**Tech Stack:** Python 3.12, math (stdlib), pytest, MagicMock, SQLAlchemy async.

---

## Contexto técnico essencial

O `Device` já tem os campos:
- `position_x: float | None` — coordenada SVG X (0–800)
- `position_y: float | None` — coordenada SVG Y (0–556)
- `influence_radius_m: int` — raio de influência em metros (default 8m; 14px/m = 112px)

Esses campos existem no banco e são usados pelo frontend para renderizar o heatmap. O backend agora usa esses campos para automação espacial; o fallback sem hotspot continua usando BTU e delta_temp.

Hotspot = centroide ponderado pelas temperaturas dos devices mais quentes da zona. Se os 3 ACs ligados têm leituras diferentes (ex: AC1=28°C perto da área fria, AC2=28°C e AC3=27.8°C perto dos ACs desligados), o centroide cai próximo dos ACs desligados → eles ganham prioridade de power_on.

---

## Mapa de arquivos

| Arquivo | O que muda |
|---|---|
| `backend/app/services/thermal_spatial.py` | Criar: `DevicePoint`, `Hotspot`, `detect_hotspot()`, `proximity_score()` |
| `backend/app/services/zone_controller.py` | Modificar: `_select_power_on_candidate`, `_select_best_device`, `_evaluate_zone`, `_build_power_on_reason`, `_build_reason` |
| `backend/tests/test_spatial_automation.py` | Criar: testes de hotspot, proximidade e seleção espacial |

---

## Task 1 — Criar thermal_spatial.py (módulo de análise espacial)

**Files:**
- Create: `backend/app/services/thermal_spatial.py`
- Create: `backend/tests/test_spatial_automation.py` (apenas os testes de thermal_spatial por agora)

- [ ] **Step 1.1 — Criar o arquivo de testes com os testes de thermal_spatial**

Criar `backend/tests/test_spatial_automation.py`:

```python
"""Testes para automação térmica espacial.

Parte 1: funções puras de thermal_spatial.
Parte 2: seleção espacial de devices em zone_controller (adicionada em Task 2).
"""
import math
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.thermal_spatial import (
    DevicePoint,
    Hotspot,
    HOTSPOT_VARIANCE_THRESHOLD,
    detect_hotspot,
    proximity_score,
)


def _dp(name, x, y, temp, is_on=True, influence_radius_m=8):
    return DevicePoint(
        device_id=str(uuid.uuid4()),
        device_name=name,
        pos_x=x,
        pos_y=y,
        influence_radius_m=float(influence_radius_m),
        temperature=temp,
        is_on=is_on,
        is_off=not is_on,
        is_available=True,
        btu=12000,
    )


# ── detect_hotspot ─────────────────────────────────────────────────────────────

def test_hotspot_none_when_single_device():
    """Apenas 1 device com temperatura → não pode detectar variância → None."""
    assert detect_hotspot([_dp("AC1", 400, 200, 27.0)]) is None


def test_hotspot_none_when_uniform_temperatures():
    """Variância < HOTSPOT_VARIANCE_THRESHOLD → sem hotspot localizado."""
    devices = [
        _dp("AC1", 100, 100, 26.0),
        _dp("AC2", 400, 200, 26.3),
        _dp("AC3", 700, 300, 25.9),
    ]
    # max - min = 0.4 < 1.5
    assert detect_hotspot(devices) is None


def test_hotspot_none_when_no_temperature_data():
    """Devices sem temperatura → None."""
    d = DevicePoint(
        device_id=str(uuid.uuid4()), device_name="AC1",
        pos_x=100, pos_y=100, influence_radius_m=8.0,
        temperature=None, is_on=False, is_off=True, is_available=True, btu=12000,
    )
    assert detect_hotspot([d]) is None


def test_hotspot_detected_with_variance():
    """Dois devices quentes longe de um frio → hotspot perto dos quentes."""
    devices = [
        _dp("HOT1", 380, 90, 28.0),
        _dp("HOT2", 420, 110, 27.5),
        _dp("COOL1", 100, 400, 25.0),  # variância 3.0°C > 1.5
    ]
    h = detect_hotspot(devices)
    assert h is not None
    assert h.peak_temp == 28.0
    assert "HOT1" in h.contributing_names or "HOT2" in h.contributing_names
    # Centroide deve estar mais próximo de (380-420, 90-110) do que de (100, 400)
    assert h.x > 200, f"Centroide x={h.x:.1f} deveria estar perto dos devices quentes"
    assert h.y < 200, f"Centroide y={h.y:.1f} deveria estar perto dos devices quentes"
    assert h.has_coordinates is True


def test_hotspot_has_coordinates_false_when_no_positions():
    """Hotspot detectado pela temperatura mas sem posições → has_coordinates=False."""
    devices = [
        DevicePoint(str(uuid.uuid4()), "AC1", None, None, 8.0, 28.0, True, False, True, 12000),
        DevicePoint(str(uuid.uuid4()), "AC2", None, None, 8.0, 25.0, True, False, True, 12000),
    ]
    # variância = 3.0 → hotspot detectado
    h = detect_hotspot(devices)
    assert h is not None
    assert h.has_coordinates is False


# ── proximity_score ────────────────────────────────────────────────────────────

def test_proximity_score_returns_half_when_no_hotspot():
    """Sem hotspot → score neutro 0.5."""
    assert proximity_score(400, 200, hotspot=None) == 0.5


def test_proximity_score_returns_half_when_no_coordinates():
    """Device sem coordenadas → score neutro 0.5."""
    h = Hotspot(x=400, y=200, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=True)
    assert proximity_score(None, None, hotspot=h) == 0.5


def test_proximity_score_high_at_hotspot_center():
    """Device exatamente no centro → score > 0.95."""
    h = Hotspot(x=400, y=200, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=True)
    score = proximity_score(400, 200, hotspot=h)
    assert score > 0.95, f"Esperava > 0.95 no centro, obteve {score}"


def test_proximity_score_decreases_with_distance():
    """Device distante deve ter score menor que device próximo."""
    h = Hotspot(x=400, y=200, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=True)
    score_near = proximity_score(410, 210, hotspot=h)     # ~14px
    score_far  = proximity_score(100, 400, hotspot=h)     # ~360px
    assert score_near > score_far, f"near={score_near:.3f} deve ser > far={score_far:.3f}"


def test_proximity_score_returns_half_when_hotspot_no_coords():
    """Hotspot sem coordenadas → score neutro 0.5."""
    h = Hotspot(x=0, y=0, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=False)
    assert proximity_score(400, 200, hotspot=h) == 0.5
```

- [ ] **Step 1.2 — Rodar para confirmar falha**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/test_spatial_automation.py -v 2>&1 | head -20
```

Saída esperada: `ModuleNotFoundError: No module named 'app.services.thermal_spatial'`

- [ ] **Step 1.3 — Criar thermal_spatial.py**

Criar `backend/app/services/thermal_spatial.py`:

```python
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
```

- [ ] **Step 1.4 — Rodar para confirmar que os testes passam**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/test_spatial_automation.py -v 2>&1
```

Saída esperada: `10 passed`

- [ ] **Step 1.5 — Commit**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO" && \
  git add backend/app/services/thermal_spatial.py backend/tests/test_spatial_automation.py && \
  git commit -m "feat: thermal_spatial — detect_hotspot e proximity_score para automação espacial"
```

---

## Task 2 — Seleção espacial nos helpers de zone_controller

**Files:**
- Modify: `backend/app/services/zone_controller.py` (funções `_select_power_on_candidate` e `_select_best_device`)
- Modify: `backend/tests/test_spatial_automation.py` (adicionar testes de seleção)

- [ ] **Step 2.1 — Adicionar testes de seleção espacial ao final de test_spatial_automation.py**

Abrir `backend/tests/test_spatial_automation.py` e adicionar ao **final do arquivo**:

```python
# ── Seleção espacial de devices ────────────────────────────────────────────────

from app.services.zone_controller import (
    _DeviceRow,
    _select_best_device,
    _select_power_on_candidate,
)


def _make_device(device_id, name, pos_x, pos_y, btu=12000, dnd=False, source_url=None, influence_radius_m=8):
    d = MagicMock()
    d.id = device_id
    d.name = name
    d.position_x = pos_x
    d.position_y = pos_y
    d.btu = btu
    d.dnd = dnd
    d.source_url = source_url
    d.influence_radius_m = influence_radius_m
    return d


def _make_status(classification, temperature=None, state=None, delta_temp=None):
    s = MagicMock()
    s.status_classification = classification
    s.temperature = temperature
    s.state = state
    s.delta_temp = delta_temp
    return s


def _make_params(device_id, setpoint_cool=22, mode_device=1):
    p = MagicMock()
    p.device_id = device_id
    p.setpoint_cool = setpoint_cool
    p.mode_device = mode_device
    p.id = device_id
    p.fan_speed = 2
    p.setpoint_heat = 28
    p.eco_cool = False
    p.eco_heat = False
    return p


def test_power_on_prefers_device_near_hotspot():
    """
    Cenário central do spec: 3 ON, 2 OFF. Hotspot em (400, 100).
    OFF_NEAR em (390, 110) — ~14px do hotspot.
    OFF_FAR em (50, 450)  — ~500px do hotspot.
    Sistema deve selecionar OFF_NEAR.
    """
    id_on1, id_on2, id_on3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    id_off_near, id_off_far = uuid.uuid4(), uuid.uuid4()

    hotspot = Hotspot(x=400, y=100, peak_temp=28.0, avg_hotspot_temp=27.5, has_coordinates=True)

    devices = [
        _DeviceRow(_make_device(id_on1, "ON1", 390, 95),   _make_status("NORMAL", 28.0, True)),
        _DeviceRow(_make_device(id_on2, "ON2", 410, 105),  _make_status("NORMAL", 27.8, True)),
        _DeviceRow(_make_device(id_on3, "ON3", 50, 450),   _make_status("NORMAL", 25.0, True)),
        _DeviceRow(_make_device(id_off_near, "OFF_NEAR", 390, 110), _make_status("DESLIGADO", None, False)),
        _DeviceRow(_make_device(id_off_far,  "OFF_FAR",  50, 450),  _make_status("DESLIGADO", None, False)),
    ]
    params_map = {
        id_on1: _make_params(id_on1, mode_device=1),
        id_on2: _make_params(id_on2, mode_device=1),
        id_on3: _make_params(id_on3, mode_device=1),
        id_off_near: _make_params(id_off_near, mode_device=0),
        id_off_far:  _make_params(id_off_far,  mode_device=0),
    }

    result = _select_power_on_candidate(devices, params_map, hotspot=hotspot)
    assert result is not None
    selected, _ = result
    assert selected.device.name == "OFF_NEAR", (
        f"Esperava OFF_NEAR (próximo ao hotspot), obteve {selected.device.name}"
    )


def test_power_on_fallback_to_btu_without_hotspot():
    """Sem hotspot: seleção cai no BTU mais alto."""
    id_big, id_small = uuid.uuid4(), uuid.uuid4()
    devices = [
        _DeviceRow(_make_device(id_big,   "AC_BIG",   200, 200, btu=24000), _make_status("DESLIGADO", None, False)),
        _DeviceRow(_make_device(id_small, "AC_SMALL", 400, 300, btu=9000),  _make_status("DESLIGADO", None, False)),
    ]
    params_map = {
        id_big:   _make_params(id_big,   mode_device=0),
        id_small: _make_params(id_small, mode_device=0),
    }
    result = _select_power_on_candidate(devices, params_map, hotspot=None)
    assert result is not None
    selected, _ = result
    assert selected.device.name == "AC_BIG", (
        f"Sem hotspot, esperava AC_BIG (maior BTU), obteve {selected.device.name}"
    )


def test_setpoint_prefers_device_near_hotspot():
    """
    3 ACs ON. Hotspot em (400, 100).
    AC_FAR tem maior delta_temp (3.5) mas está em (50, 450).
    AC_NEAR tem delta=2.0 e está em (395, 98) — muito próximo do hotspot.
    Sistema deve selecionar AC_NEAR (proximidade supera urgência).
    """
    id_near, id_mid, id_far = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    hotspot = Hotspot(x=400, y=100, peak_temp=28.0, avg_hotspot_temp=27.5, has_coordinates=True)

    readable = [
        _DeviceRow(_make_device(id_near, "AC_NEAR", 395,  98), _make_status("HOT", 28.0, True, delta_temp=2.0)),
        _DeviceRow(_make_device(id_mid,  "AC_MID",  410, 110), _make_status("HOT", 27.5, True, delta_temp=1.5)),
        _DeviceRow(_make_device(id_far,  "AC_FAR",   50, 450), _make_status("HOT", 29.5, True, delta_temp=3.5)),
    ]
    params_map = {
        id_near: _make_params(id_near, setpoint_cool=22),
        id_mid:  _make_params(id_mid,  setpoint_cool=22),
        id_far:  _make_params(id_far,  setpoint_cool=22),
    }

    result = _select_best_device(readable, "HOT", params_map, "down", 18, 28, hotspot=hotspot)
    assert result is not None
    selected, _ = result
    assert selected.device.name == "AC_NEAR", (
        f"Esperava AC_NEAR (próximo ao hotspot), obteve {selected.device.name}"
    )


def test_setpoint_fallback_to_delta_temp_without_hotspot():
    """Sem hotspot: seleção cai no maior |delta_temp|."""
    id_urgent, id_mild = uuid.uuid4(), uuid.uuid4()
    readable = [
        _DeviceRow(_make_device(id_urgent, "AC_URGENT", 100, 100), _make_status("CRITICAL", 30.0, True, delta_temp=4.0)),
        _DeviceRow(_make_device(id_mild,   "AC_MILD",   400, 300), _make_status("HOT",      26.5, True, delta_temp=1.0)),
    ]
    params_map = {
        id_urgent: _make_params(id_urgent, setpoint_cool=22),
        id_mild:   _make_params(id_mild,   setpoint_cool=22),
    }
    result = _select_best_device(readable, "CRITICAL", params_map, "down", 18, 28, hotspot=None)
    assert result is not None
    selected, _ = result
    assert selected.device.name == "AC_URGENT", (
        f"Sem hotspot, esperava AC_URGENT (maior delta_temp), obteve {selected.device.name}"
    )


def test_power_on_returns_none_when_no_off_devices():
    """Nenhum device OFF → None."""
    id1 = uuid.uuid4()
    devices = [_DeviceRow(_make_device(id1, "AC1", 400, 200), _make_status("NORMAL", 26.0, True))]
    params_map = {id1: _make_params(id1, mode_device=1)}
    assert _select_power_on_candidate(devices, params_map) is None


def test_setpoint_excludes_devices_at_setpoint_limit():
    """Device já no setpoint mínimo não é candidato para direção 'down'."""
    id_at_min, id_ok = uuid.uuid4(), uuid.uuid4()
    readable = [
        _DeviceRow(_make_device(id_at_min, "AT_MIN", 400, 200), _make_status("HOT", 28.0, True, delta_temp=3.0)),
        _DeviceRow(_make_device(id_ok,     "OK",     100, 100), _make_status("HOT", 27.0, True, delta_temp=2.0)),
    ]
    params_map = {
        id_at_min: _make_params(id_at_min, setpoint_cool=18),  # já no mínimo
        id_ok:     _make_params(id_ok,     setpoint_cool=22),
    }
    result = _select_best_device(readable, "HOT", params_map, "down", 18, 28)
    assert result is not None
    selected, _ = result
    assert selected.device.name == "OK", f"Obteve {selected.device.name}, esperava OK"
```

- [ ] **Step 2.2 — Rodar para confirmar que os novos testes falham**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/test_spatial_automation.py -v -k "power_on_prefers or setpoint_prefers or fallback_to_btu or fallback_to_delta" 2>&1 | head -40
```

Saída esperada: `FAILED` nos testes de seleção (funções ainda não aceitam `hotspot`)

- [ ] **Step 2.3 — Substituir `_select_power_on_candidate` em zone_controller.py**

Localizar as linhas 812–847 de `backend/app/services/zone_controller.py`. Substituir a função **completa**:

```python
def _select_power_on_candidate(
    devices: list[_DeviceRow],
    params_map: dict[uuid.UUID, DeviceParameters],
    hotspot=None,  # Hotspot | None — lazy typed para evitar import circular
) -> tuple[_DeviceRow, DeviceParameters] | None:
    from app.services.thermal_spatial import proximity_score as _prox

    candidates = []
    for row in devices:
        if row.device.dnd or row.device.source_url:
            continue
        params = params_map.get(row.device.id)
        is_off = (
            row.status.status_classification == "DESLIGADO"
            or row.status.state is False
            or (params is not None and params.mode_device == 0)
        )
        if is_off:
            candidates.append(row)

    if not candidates:
        return None

    def sort_key(row: _DeviceRow) -> tuple[float, float]:
        prox = _prox(
            row.device.position_x,
            row.device.position_y,
            hotspot,
            float(row.device.influence_radius_m or 8),
        )
        btu_norm = (row.device.btu or 12000) / 36000.0
        return (prox, btu_norm)

    candidates.sort(key=sort_key, reverse=True)
    best = candidates[0]
    params = params_map.get(best.device.id)
    if params is None:
        params = DeviceParameters(
            device_id=best.device.id,
            mode_device=0,
            mode_ac=0,
            fan_speed=1,
            setpoint_cool=22,
            setpoint_heat=28,
            eco_cool=False,
            eco_heat=False,
        )
    return best, params
```

- [ ] **Step 2.4 — Substituir `_select_best_device` em zone_controller.py**

Localizar as linhas 782–809. Substituir a função **completa**:

```python
def _select_best_device(
    readable: list[_DeviceRow],
    status: str,
    params_map: dict[uuid.UUID, DeviceParameters],
    direction: str,
    setpoint_min: int,
    setpoint_max: int,
    hotspot=None,  # Hotspot | None
) -> tuple[_DeviceRow, DeviceParameters] | None:
    from app.services.thermal_spatial import proximity_score as _prox

    going_down = direction == "down"
    candidates = [
        r for r in readable
        if r.device.id in params_map
        and not r.device.source_url
        and (params_map[r.device.id].setpoint_cool > setpoint_min if going_down
             else params_map[r.device.id].setpoint_cool < setpoint_max)
    ]
    if not candidates:
        return None

    def sort_key(row: _DeviceRow) -> tuple[float, float]:
        prox = _prox(
            row.device.position_x,
            row.device.position_y,
            hotspot,
            float(row.device.influence_radius_m or 8),
        )
        delta = row.status.delta_temp
        delta_norm = abs(delta) / 10.0 if delta is not None else 0.0
        return (prox, delta_norm)

    candidates.sort(key=sort_key, reverse=True)
    best = candidates[0]
    return best, params_map[best.device.id]
```

- [ ] **Step 2.5 — Rodar todos os testes**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/test_spatial_automation.py -v 2>&1
```

Saída esperada: `21 passed` (10 de thermal_spatial + 6 novos de seleção + 5 existentes de test_spatial parte 1)

> Se algum teste falhar por importação (módulo não encontrado ao importar zone_controller), verificar:
> ```bash
> cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -c "from app.services.zone_controller import _select_power_on_candidate; print('OK')"
> ```

- [ ] **Step 2.6 — Commit**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO" && \
  git add backend/app/services/zone_controller.py backend/tests/test_spatial_automation.py && \
  git commit -m "feat: seleção espacial em zone_controller — hotspot prioriza device próximo antes de BTU/delta_temp"
```

---

## Task 3 — Wire hotspot detection em `_evaluate_zone` + melhorar mensagens

**Files:**
- Modify: `backend/app/services/zone_controller.py` (funções `_evaluate_zone`, `_build_power_on_reason`, `_build_reason`)

- [ ] **Step 3.1 — Adicionar detecção de hotspot em `_evaluate_zone`**

Em `backend/app/services/zone_controller.py`, localizar o bloco (linhas ~380–404):

```python
        temp_sources = [
            d for d in devices
            if d.status.temperature is not None
            and d.status.status_classification not in BLOCKED_STATUSES
            and not d.device.dnd
        ]

        # Fallback: ACs classificados como DESLIGADO mas ainda reportando temperatura.
```

Substituir por:

```python
        temp_sources = [
            d for d in devices
            if d.status.temperature is not None
            and d.status.status_classification not in BLOCKED_STATUSES
            and not d.device.dnd
        ]

        # Detecta hotspot a partir das leituras reais (antes do fallback, para não usar dados suspeitos)
        hotspot = None
        if temp_sources:
            from app.services.thermal_spatial import DevicePoint, detect_hotspot
            _device_points = [
                DevicePoint(
                    device_id=str(d.device.id),
                    device_name=d.device.name,
                    pos_x=d.device.position_x,
                    pos_y=d.device.position_y,
                    influence_radius_m=float(d.device.influence_radius_m or 8),
                    temperature=float(d.status.temperature),
                    is_on=d.status.state is True,
                    is_off=d.status.status_classification == "DESLIGADO",
                    is_available=not d.device.dnd and not d.device.source_url,
                    btu=d.device.btu or 12000,
                )
                for d in temp_sources
            ]
            hotspot = detect_hotspot(_device_points)
            if hotspot:
                logger.debug(
                    "Zone %s: hotspot (%.0f,%.0f) pico=%.1f°C — devices quentes: %s",
                    zone.key, hotspot.x, hotspot.y, hotspot.peak_temp,
                    ", ".join(hotspot.contributing_names),
                )

        # Fallback: ACs classificados como DESLIGADO mas ainda reportando temperatura.
```

- [ ] **Step 3.2 — Passar `hotspot` para `_select_power_on_candidate`**

Localizar (linha ~482):

```python
        power_on_candidate = _select_power_on_candidate(devices, params_map) if direction == "down" else None
```

Substituir por:

```python
        power_on_candidate = _select_power_on_candidate(devices, params_map, hotspot=hotspot) if direction == "down" else None
```

- [ ] **Step 3.3 — Passar `hotspot` para `_build_power_on_reason`**

Localizar (linha ~486):

```python
            reason = _build_power_on_reason(avg_temp, zone, status, power_device.device, trend)
```

Substituir por:

```python
            reason = _build_power_on_reason(avg_temp, zone, status, power_device.device, trend, hotspot=hotspot)
```

- [ ] **Step 3.4 — Passar `hotspot` para `_select_best_device`**

Localizar (linha ~561):

```python
        best = _select_best_device(readable, status, params_map, direction, automation.setpoint_min, automation.setpoint_max)
```

Substituir por:

```python
        best = _select_best_device(readable, status, params_map, direction, automation.setpoint_min, automation.setpoint_max, hotspot=hotspot)
```

- [ ] **Step 3.5 — Passar `hotspot` para `_build_reason`**

Localizar (linha ~594):

```python
        reason = _build_reason(avg_temp, zone, status, best_device.device, direction, trend)
```

Substituir por:

```python
        reason = _build_reason(avg_temp, zone, status, best_device.device, direction, trend, hotspot=hotspot)
```

- [ ] **Step 3.6 — Substituir `_build_power_on_reason` com suporte a hotspot**

Localizar as linhas ~1112–1130. Substituir a função **completa**:

```python
def _build_power_on_reason(
    avg: float,
    zone: ZoneConfig,
    status: str,
    device: Device,
    trend: float | None = None,
    hotspot=None,  # Hotspot | None
) -> str:
    labels = {"WARM": "zona aquecendo", "HOT": "zona quente", "CRITICAL": "zona crítica"}
    label = labels.get(status, status)
    wall_note = (
        " [SALA_FECHADA — aparelho interno da sala usado.]"
        if zone.zone_type == "SALA_FECHADA" else ""
    )
    trend_note = f" Tendência {trend:+.1f}°C/h." if trend is not None else ""

    if hotspot and hotspot.has_coordinates and hotspot.contributing_names:
        hot_names = ", ".join(hotspot.contributing_names[:2])
        spatial_note = (
            f" Hotspot identificado próximo a {hot_names} ({hotspot.peak_temp:.1f}°C);"
            f" {device.name} selecionado por proximidade ao ponto quente."
        )
    else:
        spatial_note = ""

    return (
        f"Temperatura média {avg:.1f}°C ({label}).{trend_note}{spatial_note} "
        f"Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ligar {device.name} (desligado) para aumentar capacidade de resfriamento na subárea quente.{wall_note}"
    )
```

- [ ] **Step 3.7 — Substituir `_build_reason` com suporte a hotspot**

Localizar as linhas ~1133–1154. Substituir a função **completa**:

```python
def _build_reason(
    avg: float,
    zone: ZoneConfig,
    status: str,
    device: Device,
    direction: str,
    trend: float | None = None,
    hotspot=None,  # Hotspot | None
) -> str:
    direction_pt = "reduzir" if direction == "down" else "aumentar"
    labels = {"WARM": "zona aquecendo", "HOT": "zona quente", "CRITICAL": "zona crítica", "COLD": "zona fria"}
    label = labels.get(status, status)
    wall_note = (
        " [SALA_FECHADA — aparelho interno da sala usado.]"
        if zone.zone_type == "SALA_FECHADA" else ""
    )
    trend_note = f" Tendência {trend:+.1f}°C/h." if trend is not None else ""
    step = _step_size(status)

    if hotspot and hotspot.has_coordinates and hotspot.contributing_names:
        hot_names = ", ".join(hotspot.contributing_names[:2])
        spatial_note = (
            f" Hotspot em {hot_names} ({hotspot.peak_temp:.1f}°C);"
            f" {device.name} selecionado por influência espacial na subárea quente."
        )
    else:
        spatial_note = ""

    return (
        f"Temperatura média {avg:.1f}°C ({label}).{trend_note}{spatial_note} "
        f"Faixa ideal {zone.ideal_min}–{zone.ideal_max}°C. "
        f"Ajuste via {device.name} para {direction_pt} {step}°C no setpoint.{wall_note}"
    )
```

- [ ] **Step 3.8 — Verificar importações**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -c "
from app.services.zone_controller import run_zone_controller
from app.services.thermal_spatial import detect_hotspot, proximity_score
print('OK')
"
```

Saída esperada: `OK`

- [ ] **Step 3.9 — Rodar todos os testes**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/ -v 2>&1
```

Saída esperada: todos passando (11 anteriores + 16 novos de spatial = pelo menos 21 tests)

- [ ] **Step 3.10 — Commit**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO" && \
  git add backend/app/services/zone_controller.py && \
  git commit -m "feat: wire hotspot em _evaluate_zone; mensagens incluem subárea quente e device selecionado por proximidade"
```

---

## Task 4 — Deploy

- [ ] **Step 4.1 — Verificar imports no container**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -c "
from app.services.zone_controller import run_zone_controller, _select_power_on_candidate, _select_best_device
from app.services.thermal_spatial import detect_hotspot, proximity_score, Hotspot, DevicePoint
print('OK')
"
```

- [ ] **Step 4.2 — Rodar suite completa de testes**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend" && PYTHONPATH=. python -m pytest tests/ -v 2>&1
```

Saída esperada: todos passando, nenhum erro.

- [ ] **Step 4.3 — Deploy para Azure**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO" && bash deploy.sh latest 2>&1
```

---

## Self-review

### Cobertura do spec

| Requisito | Task |
|---|---|
| Não usar só média da zona | Task 3 — hotspot composto antes da seleção |
| Criar lógica de hotspot térmico | Task 1 — detect_hotspot() com centroide ponderado |
| Relacionar hotspot com aparelhos próximos | Task 1 — proximity_score(); Task 2 — sort_key |
| Regra de decisão correta (OFF near hotspot first) | Task 2 — _select_power_on_candidate com hotspot |
| Conceito de influência/cobertura | Task 1 — influence_radius_m como ref_radius |
| Priorizar ligar antes de compensar | Task 2 — poder_on_candidate usa proximity como chave primária |
| Evitar decisões globais ruins | Task 2 — sort_key não usa só BTU/delta global |
| Melhorar camada de dados do mapa | Device.position_x/y e influence_radius_m já existem; agora usados |
| Heurística mínima sem modelagem física | Task 1 — exponential decay por distância SVG |
| Mensagens e diagnósticos espaciais | Task 3 — _build_power_on_reason e _build_reason |
| Dois níveis (global + local) | avg_temp global (existente) + hotspot local (novo) |
| Regras de validação | Guardrails existentes inalterados (DND, bloqueado, no-op) |
| Testes obrigatórios | Tasks 1, 2 — test_spatial_automation.py com 16 testes |
| Critério de aceite final | test_power_on_prefers_device_near_hotspot cobre o cenário exato |

### Scan de placeholders

Nenhum TBD, nenhum "implementar depois", todo código completo.

### Consistência de tipos

- `Hotspot` definido em `thermal_spatial.py`; usado como `hotspot=None` (lazy typed) em zone_controller
- `DevicePoint` criado em `_evaluate_zone` com todos os campos obrigatórios
- `proximity_score(pos_x, pos_y, hotspot, influence_radius_m)` — assinatura consistente em todos os call sites
- `detect_hotspot(list[DevicePoint])` — sempre recebe lista de DevicePoint

### Compatibilidade com código existente

- `_select_power_on_candidate(devices, params_map)` — chamada antiga ainda funciona (hotspot=None por default → fallback a BTU)
- `_select_best_device(readable, status, params_map, direction, setpoint_min, setpoint_max)` — idem
- `_build_power_on_reason(avg, zone, status, device, trend)` — idem (hotspot=None → sem spatial_note)
- Nenhum teste existente quebrado
