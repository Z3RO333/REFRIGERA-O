"""Testes para _device_window_ok — proteção por janela de 15 min por device."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.zone_controller import (
    DEVICE_WINDOW_MAX_CMDS,
    _device_window_ok,
)


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
    assert "IF EXISTS" in source
