"""Fixtures compartilhadas para todos os testes."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.zone import ZoneAutomation


@pytest.fixture
def store_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def zone_key() -> str:
    return "FARMA"


@pytest.fixture
def automation(store_id) -> ZoneAutomation:
    a = ZoneAutomation()
    a.id = uuid.uuid4()
    a.store_id = store_id
    a.zone_key = "FARMA"
    a.mode = "auto"
    a.setpoint_min = 18
    a.setpoint_max = 28
    a.allowed_start_hour = 0
    a.allowed_end_hour = 23
    a.allowed_start_minute = 0
    a.allowed_end_minute = 59
    a.is_critical_zone = False
    a.priority = "conforto"
    a.zone_type = "ABERTA"
    a.reading_confidence = 1.0
    a.blocked_reason = None
    a.blocked_until = None
    a.blocked_by_user_name = None
    a.blocked_at = None
    return a


@pytest.fixture
def mock_redis():
    m = MagicMock()
    m.exists = AsyncMock(return_value=False)
    m.set = AsyncMock()
    m.acquire_lock = AsyncMock(return_value=True)
    m.release_lock = AsyncMock()
    m.incr = AsyncMock(return_value=1)
    m.expire = AsyncMock()
    m.client = MagicMock()
    pipe = AsyncMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.incr = AsyncMock()
    pipe.expire = AsyncMock()
    pipe.execute = AsyncMock(return_value=[1, True])
    m.client.pipeline = MagicMock(return_value=pipe)
    return m
