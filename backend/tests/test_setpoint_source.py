"""Regressões para separar setpoint real da faixa ideal da zona."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from app.api.v1 import devices as devices_api


def test_brise_params_24_vira_current_setpoint_24():
    brise = MagicMock()
    brise.modeDevice = 1
    brise.modeAC = 0
    brise.fanSpeed = 2
    brise.setpointCool = 24
    brise.setpointHeat = 20
    brise.ecoCool = 22
    brise.ecoHeat = 18

    params = devices_api._brise_params_to_dict(brise)

    assert params["setpoint_cool"] == 24


def test_faixa_ideal_nao_sobrescreve_current_setpoint():
    db_params = MagicMock()
    db_params.setpoint_cool = 24
    db_params.synced_at = datetime.utcnow()

    payload = {"ideal_min": 20, "ideal_max": 24}
    devices_api._enrich_parameter_fields(payload, db_params)

    assert payload["current_setpoint"] == 24
    assert payload["setpoint_cool"] == 24
    assert payload["ideal_min"] == 20
    assert payload["setpoint_stale"] is False


def test_setpoint_stale_e_marcado_sem_assumir_como_atual_confiavel():
    db_params = MagicMock()
    db_params.setpoint_cool = 20
    db_params.synced_at = datetime.utcnow() - timedelta(minutes=90)

    payload = {}
    devices_api._enrich_parameter_fields(payload, db_params)

    assert payload["current_setpoint"] == 20
    assert payload["setpoint_stale"] is True
    assert payload["setpoint_synced_at"] is not None


def test_frontend_nao_usa_faixa_ideal_como_limite_de_setpoint():
    source = Path("../frontend/src/pages/ThermalComfortMap.tsx").read_text()

    assert "Math.max(zone.idealMin, currentSp - 1)" not in source
    assert "Math.min(zone.idealMax, currentSp + 1)" not in source
    assert "Setpoint já no limite da faixa ideal" not in source
    assert "Math.max(minAllowedSp, currentSp - 1)" in source
    assert "Setpoint atual real" in source
