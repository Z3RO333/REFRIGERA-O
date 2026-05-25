"""Testes para classify_status — comportamento determinístico."""
from datetime import datetime, timedelta

import pytest

from app.rules.classifier import (
    STATUS_NORMAL,
    STATUS_OFF,
    STATUS_NO_READING,
    STATUS_WARNING,
    STATUS_CRITICAL,
    classify_status,
)


def _base_kwargs(**overrides):
    return {
        "state": True,
        "temperature": 24.0,
        "setpoint_cool": 24,
        "mode_ac": 0,
        "btu": 12000,
        "consumption_estimated": None,
        "last_reading_time": None,
        "consecutive_count": 3,
        "current_status": None,
        **overrides,
    }


def test_state_false_classifica_como_desligado():
    """state=False deve retornar STATUS_OFF independente da temperatura."""
    status, delta, eff = classify_status(**_base_kwargs(state=False, temperature=25.0))
    assert status == STATUS_OFF
    assert delta is None
    assert eff is None


def test_temperatura_none_classifica_sem_leitura():
    """Temperatura None com state=True deve retornar STATUS_NO_READING."""
    status, _, _ = classify_status(**_base_kwargs(temperature=None))
    assert status == STATUS_NO_READING


def test_leitura_antiga_classifica_sem_leitura():
    """Leitura com mais de 15 min deve retornar STATUS_NO_READING."""
    old_time = datetime.utcnow() - timedelta(minutes=20)
    status, _, _ = classify_status(**_base_kwargs(last_reading_time=old_time))
    assert status == STATUS_NO_READING


def test_temperatura_dentro_da_faixa_normal():
    """Temperatura dentro da faixa ideal deve ser NORMAL."""
    status, _, _ = classify_status(
        **_base_kwargs(temperature=23.0, zone_ideal_min=22.0, zone_ideal_max=24.0)
    )
    assert status == STATUS_NORMAL


def test_temperatura_acima_da_faixa_critica():
    """Temperatura muito acima da faixa com leituras consecutivas deve ser CRITICAL.

    zone_ideal_max=24.0, temperatura=29.0 → zone_excess=5.0 > _ZONE_HOT_DELTA(3.5)
    e consecutive_count=5 >= CONSECUTIVE_READINGS_REQUIRED(3).
    """
    status, _, _ = classify_status(
        **_base_kwargs(
            temperature=29.0,
            zone_ideal_min=22.0,
            zone_ideal_max=24.0,
            consecutive_count=5,
        )
    )
    assert status == STATUS_CRITICAL


def test_modo_fan_only_classifica_normal():
    """AC em modo fan (mode_ac=1, não é 0 nem 2) retorna NORMAL com delta e eff nulos."""
    status, delta, eff = classify_status(
        **_base_kwargs(temperature=30.0, mode_ac=1)
    )
    assert status == STATUS_NORMAL
    assert delta is None
    assert eff is None
