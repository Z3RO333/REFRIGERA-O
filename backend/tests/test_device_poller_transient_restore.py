import uuid
from datetime import datetime, timedelta

from app.models.device import DeviceStatusLatest
from app.models.reading import DeviceReading
from app.polling.device_poller import (
    _apply_last_good_reading_to_status,
    _latest_status_needs_restore,
)
from app.rules.classifier import STATUS_NO_READING


def test_latest_status_needs_restore_when_latest_was_wiped_to_no_reading():
    status = DeviceStatusLatest(
        device_id=uuid.uuid4(),
        status_classification=STATUS_NO_READING,
        temperature=None,
    )

    assert _latest_status_needs_restore(status) is True


def test_transient_brise_error_restores_latest_from_last_good_reading():
    device_id = uuid.uuid4()
    old_time = datetime.utcnow() - timedelta(minutes=35)
    now = datetime.utcnow()
    status = DeviceStatusLatest(
        device_id=device_id,
        status_classification=STATUS_NO_READING,
        temperature=None,
        consecutive_readings_count=0,
        consecutive_failures=2,
    )
    last_good = DeviceReading(
        device_id=device_id,
        time=old_time,
        state=True,
        temperature=23.7,
        humidity=61.0,
        consumption=10.5,
        consumption_estimated=1.2,
        status_classification="NORMAL",
        delta_temp=0.4,
        efficiency_score=92.0,
        accumulated_on_minutes=180,
        accumulated_off_minutes=20,
    )

    _apply_last_good_reading_to_status(
        status,
        last_good,
        "Falha transitória na API Brise após retentativas (RetryError)",
        now,
    )

    assert status.status_classification == "NORMAL"
    assert status.temperature == 23.7
    assert status.state is True
    assert status.updated_at == old_time
    assert status.last_success_at == old_time
    assert status.last_error.startswith("Falha transitória")
    assert status.last_error_at == now
    assert status.consecutive_failures == 3
