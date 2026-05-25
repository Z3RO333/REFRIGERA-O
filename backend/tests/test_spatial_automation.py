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
