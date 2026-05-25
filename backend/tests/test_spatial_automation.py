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


# ── Spatial selection in zone_controller helpers ───────────────────────────────

def _make_device_row(name, x, y, btu, influence_radius_m=8, delta_temp=2.0, setpoint_cool=22):
    """Build a minimal _DeviceRow-like object for testing selection helpers."""
    device = MagicMock()
    device.id = uuid.uuid4()
    device.name = name
    device.btu = btu
    device.position_x = x
    device.position_y = y
    device.influence_radius_m = influence_radius_m
    device.source_url = None
    device.dnd = False

    status = MagicMock()
    status.delta_temp = delta_temp
    status.status_classification = "LIGADO"
    status.state = True

    params = MagicMock()
    params.mode_device = 1
    params.setpoint_cool = setpoint_cool

    row = MagicMock()
    row.device = device
    row.status = status
    return row, params


def test_select_best_device_prefers_closer_to_hotspot():
    """_select_best_device should pick the device closer to the hotspot."""
    from app.services.zone_controller import _select_best_device

    hotspot = Hotspot(x=400, y=200, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=True)

    row_near, params_near = _make_device_row("NEAR", x=410, y=205, btu=9000, delta_temp=1.5, setpoint_cool=23)
    row_far,  params_far  = _make_device_row("FAR",  x=100, y=400, btu=18000, delta_temp=3.0, setpoint_cool=23)

    params_map = {row_near.device.id: params_near, row_far.device.id: params_far}

    result = _select_best_device(
        readable=[row_near, row_far],
        status="LIGADO",
        params_map=params_map,
        direction="down",
        setpoint_min=18,
        setpoint_max=26,
        hotspot=hotspot,
    )

    assert result is not None
    best_row, _ = result
    assert best_row.device.name == "NEAR", (
        f"Expected NEAR (closer to hotspot) but got {best_row.device.name}"
    )


def test_select_best_device_falls_back_to_delta_without_hotspot():
    """Without hotspot, _select_best_device falls back to highest |delta_temp|."""
    from app.services.zone_controller import _select_best_device

    row_hi, params_hi = _make_device_row("HIGH_DELTA", x=100, y=100, btu=9000, delta_temp=5.0, setpoint_cool=23)
    row_lo, params_lo = _make_device_row("LOW_DELTA",  x=400, y=200, btu=18000, delta_temp=1.0, setpoint_cool=23)

    params_map = {row_hi.device.id: params_hi, row_lo.device.id: params_lo}

    result = _select_best_device(
        readable=[row_hi, row_lo],
        status="LIGADO",
        params_map=params_map,
        direction="down",
        setpoint_min=18,
        setpoint_max=26,
        hotspot=None,
    )

    assert result is not None
    best_row, _ = result
    assert best_row.device.name == "HIGH_DELTA", (
        f"Expected HIGH_DELTA (largest delta) but got {best_row.device.name}"
    )


def test_select_power_on_prefers_closer_to_hotspot():
    """_select_power_on_candidate should pick the device closer to the hotspot."""
    from app.services.zone_controller import _select_power_on_candidate

    hotspot = Hotspot(x=400, y=200, peak_temp=28.0, avg_hotspot_temp=27.0, has_coordinates=True)

    row_near, params_near = _make_device_row("NEAR_OFF", x=415, y=195, btu=9000)
    row_far,  params_far  = _make_device_row("FAR_OFF",  x=100, y=400, btu=18000)

    # Mark both as off
    row_near.status.status_classification = "DESLIGADO"
    row_near.status.state = False
    params_near.mode_device = 0
    row_far.status.status_classification = "DESLIGADO"
    row_far.status.state = False
    params_far.mode_device = 0

    params_map = {row_near.device.id: params_near, row_far.device.id: params_far}

    result = _select_power_on_candidate(
        devices=[row_near, row_far],
        params_map=params_map,
        hotspot=hotspot,
    )

    assert result is not None
    best_row, _ = result
    assert best_row.device.name == "NEAR_OFF", (
        f"Expected NEAR_OFF (closer to hotspot) but got {best_row.device.name}"
    )


def test_select_power_on_falls_back_to_btu_without_hotspot():
    """Without hotspot, _select_power_on_candidate falls back to highest BTU."""
    from app.services.zone_controller import _select_power_on_candidate

    row_hi, params_hi = _make_device_row("HIGH_BTU", x=100, y=100, btu=18000)
    row_lo, params_lo = _make_device_row("LOW_BTU",  x=400, y=200, btu=9000)

    for row, params in [(row_hi, params_hi), (row_lo, params_lo)]:
        row.status.status_classification = "DESLIGADO"
        row.status.state = False
        params.mode_device = 0

    params_map = {row_hi.device.id: params_hi, row_lo.device.id: params_lo}

    result = _select_power_on_candidate(
        devices=[row_hi, row_lo],
        params_map=params_map,
        hotspot=None,
    )

    assert result is not None
    best_row, _ = result
    assert best_row.device.name == "HIGH_BTU", (
        f"Expected HIGH_BTU (largest BTU) but got {best_row.device.name}"
    )
