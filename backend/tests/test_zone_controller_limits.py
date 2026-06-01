"""Testes para _device_window_ok — proteção por janela de 15 min por device."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.zone_controller import (
    DEVICE_WINDOW_MAX_CMDS,
    ZoneConfig,
    _DeviceRow,
    _device_window_ok,
    _hotspot_at_setpoint_floor,
    _planned_setpoint_after,
    _should_enter_recovery,
    _should_enter_recovery_for_hotspot,
)
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.zone import ZoneAutomation
from app.services.thermal_spatial import Hotspot


def make_mock_redis(count: int):
    """Cria um mock de redis_client com pipeline que retorna `count` como resultado do INCR."""
    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.incr = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock(return_value=[count, True])

    m = MagicMock()
    m.client = MagicMock()
    m.client.pipeline = MagicMock(return_value=pipe)
    m.client.decrby = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_primeiro_comando_permitido():
    """Primeiro comando (count=1) deve ser permitido."""
    mock_redis = make_mock_redis(count=1)
    device_id = uuid.uuid4()

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is True


@pytest.mark.asyncio
async def test_exatamente_no_limite_permitido():
    """Exatamente DEVICE_WINDOW_MAX_CMDS comandos ainda deve ser permitido."""
    mock_redis = make_mock_redis(count=DEVICE_WINDOW_MAX_CMDS)
    device_id = uuid.uuid4()

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is True


@pytest.mark.asyncio
async def test_acima_do_limite_bloqueado():
    """DEVICE_WINDOW_MAX_CMDS + 1 comandos deve ser bloqueado e compensado."""
    mock_redis = make_mock_redis(count=DEVICE_WINDOW_MAX_CMDS + 1)
    device_id = uuid.uuid4()

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is False
    mock_redis.client.decrby.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_indisponivel_fail_open():
    """Se o Redis lançar exceção, deve retornar True (fail-open)."""
    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock(side_effect=ConnectionError("Redis offline"))

    mock_redis = MagicMock()
    mock_redis.client = MagicMock()
    mock_redis.client.pipeline = MagicMock(return_value=pipe)

    device_id = uuid.uuid4()

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is True


def test_sem_limite_diario_no_codigo():
    """O código-fonte não deve mais conter referência ao limite diário removido."""
    import inspect
    import app.services.zone_controller as mod

    source = inspect.getsource(mod)
    assert "Limite diário de" not in source
    assert "max_daily_adjustments" not in source or "_daily_count" not in source.split("max_daily_adjustments")[0]


def test_migration_max_daily_adjustments_eh_guardada_por_coluna_existente():
    """Banco novo sem coluna legada não pode quebrar startup na migration."""
    from pathlib import Path

    source = Path("app/db/migrations.py").read_text()
    assert "column_name='max_daily_adjustments'" in source
    assert "UPDATE zone_automations" in source
    assert "ALTER COLUMN max_daily_adjustments DROP NOT NULL" in source
    assert "ALTER COLUMN max_daily_adjustments DROP DEFAULT" in source
    assert "IF EXISTS" in source


def test_recovery_min_override_permite_descer_abaixo_do_piso_normal():
    params = DeviceParameters(device_id=uuid.uuid4(), setpoint_cool=20)
    automation = ZoneAutomation(
        store_id=uuid.uuid4(),
        zone_key="farma",
        setpoint_min=20,
        setpoint_max=28,
    )
    zone = ZoneConfig(
        key="farma",
        label="Farma",
        sector_names=[],
        ideal_min=20,
        ideal_max=24,
    )

    planned = _planned_setpoint_after(
        params,
        "down",
        zone,
        automation,
        "HOT",
        setpoint_min=18,
        setpoint_max=28,
    )

    assert planned == 19


def test_migration_tem_campos_de_recuperacao_termica():
    from pathlib import Path

    source = Path("app/db/migrations.py").read_text()
    assert "recovery_enabled" in source
    assert "recovery_min_setpoint" in source
    assert "recovery_target_setpoint" in source
    assert "recovery_max_duration_minutes" in source
    assert "was_in_recovery" in source


def test_recovery_entra_em_warm_com_margem_acima_da_faixa():
    zone = ZoneConfig(
        key="farma",
        label="Farma",
        sector_names=[],
        ideal_min=22,
        ideal_max=24,
    )

    assert _should_enter_recovery("WARM", 24.4, zone) is True
    assert _should_enter_recovery("WARM", 24.1, zone) is False
    assert _should_enter_recovery("HOT", 25.1, zone) is True


def test_recovery_entra_por_hotspot_quente_mesmo_com_media_confortavel():
    zone = ZoneConfig(
        key="farma",
        label="Farma",
        sector_names=[],
        ideal_min=22,
        ideal_max=24,
    )
    hotspot = Hotspot(
        x=10,
        y=20,
        peak_temp=26.5,
        avg_hotspot_temp=26.5,
        contributing_names=["Brise 9"],
        peak_device_name="Brise 9",
    )

    assert _should_enter_recovery_for_hotspot("HOT", hotspot, zone) is True


def test_hotspot_no_piso_normal_libera_recuperacao_local():
    device_id = uuid.uuid4()
    automation = ZoneAutomation(
        store_id=uuid.uuid4(),
        zone_key="farma",
        setpoint_min=20,
        setpoint_max=26,
    )
    row = _DeviceRow(
        Device(
            id=device_id,
            brise_device_id="123",
            name="Brise 9",
            dnd=False,
            source_url=None,
        ),
        DeviceStatusLatest(
            device_id=device_id,
            state=True,
            temperature=26.5,
            status_classification="NORMAL",
            updated_at=datetime.utcnow(),
        ),
    )
    params = DeviceParameters(
        device_id=device_id,
        mode_device=1,
        setpoint_cool=20,
    )
    hotspot = Hotspot(
        x=10,
        y=20,
        peak_temp=26.5,
        avg_hotspot_temp=26.5,
        contributing_names=["Brise 9"],
        peak_device_name="Brise 9",
    )

    assert _hotspot_at_setpoint_floor([row], {device_id: params}, automation, hotspot) is True


# ── Fim de semana ─────────────────────────────────────────────────────────────

def test_weekend_max_devices_zona_1_ac():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(1) == 0


def test_weekend_max_devices_zona_2_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(2) == 1


def test_weekend_max_devices_zona_3_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(3) == 2


def test_weekend_max_devices_zona_4_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(4) == 2


def test_weekend_max_devices_zona_0_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(0) == 0


def test_is_weekend_now_sabado():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    mock_now = MagicMock()
    mock_now.weekday.return_value = 5  # sábado

    with patch("app.services.zone_controller.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        assert _is_weekend_now() is True


def test_is_weekend_now_domingo():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    mock_now = MagicMock()
    mock_now.weekday.return_value = 6  # domingo

    with patch("app.services.zone_controller.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        assert _is_weekend_now() is True


def test_is_weekend_now_dia_util():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    for weekday in range(5):  # segunda a sexta
        mock_now = MagicMock()
        mock_now.weekday.return_value = weekday

        with patch("app.services.zone_controller.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert _is_weekend_now() is False, f"weekday={weekday} deveria retornar False"


def test_weekend_ideal_max_offset_aplicado():
    """No fim de semana, ideal_max + 2.0 move classificação de WARM para COMFORT."""
    from app.services.zone_controller import _classify

    ideal_max_original = 24.0
    temp = 25.5  # 1.5°C acima do ideal_max → WARM sem offset

    # Sem offset: 25.5 <= 24.0 + 1.5 = 25.5 → WARM
    assert _classify(temp, 22.0, ideal_max_original) == "WARM"

    # Com offset: 25.5 <= 26.0 → COMFORT
    assert _classify(temp, 22.0, ideal_max_original + 2.0) == "COMFORT"
