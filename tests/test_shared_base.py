import io
import os
import sys
from datetime import datetime, time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clock import FakeClock, SystemClock, in_time_window
from config import DEFAULTS, load_config, parse_hhmm
from masking import get_logger, mask_text


# ---------- config ----------
def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "does_not_exist.yaml"))
    assert cfg == DEFAULTS


def test_file_values_override_defaults(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text('update:\n  retry_delays_minutes: [5, 10]\nmaintenance_window:\n  start: "23:00"\n')
    cfg = load_config(str(path))
    assert cfg["update"]["retry_delays_minutes"] == [5, 10]
    assert cfg["maintenance_window"]["start"] == "23:00"
    assert cfg["maintenance_window"]["end"] == "04:00"  # untouched default
    assert cfg["health_check"]["rollback_window_minutes"] == 5


@pytest.mark.parametrize(
    "text",
    [
        "update:\n  retry_delays_minutes: []\n",
        "update:\n  retry_delays_minutes: [15, -5]\n",
        'update:\n  schedule_time: "25:99"\n',
        "update:\n  schedule_time: 10:30\n",  # unquoted time is read as a number (630): YAML trap
        "health_check:\n  rollback_window_minutes: 0\n",
        "quality_gate:\n  min_accuracy: 1.5\n",
    ],
)
def test_invalid_config_is_rejected(tmp_path, text):
    path = tmp_path / "c.yaml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_config(str(path))


def test_repository_config_file_is_valid():
    cfg = load_config()
    assert cfg["update"]["retry_delays_minutes"] == [15, 30, 60]
    assert cfg["health_check"]["rollback_window_minutes"] == 5


def test_parse_hhmm():
    assert parse_hhmm("02:30") == time(2, 30)


# ---------- clock ----------
def test_fake_clock_can_be_set_and_advanced():
    clock = FakeClock(datetime(2026, 11, 10, 1, 0))
    clock.advance(minutes=15)
    assert clock.now() == datetime(2026, 11, 10, 1, 15)
    clock.set(datetime(2027, 1, 1, 0, 0))
    assert clock.now() == datetime(2027, 1, 1, 0, 0)


def test_system_clock_returns_a_datetime():
    assert isinstance(SystemClock().now(), datetime)


def test_time_window_inside_and_outside():
    start, end = time(1, 0), time(4, 0)
    assert in_time_window(time(1, 0), start, end) is True
    assert in_time_window(time(3, 59), start, end) is True
    assert in_time_window(time(4, 0), start, end) is False
    assert in_time_window(time(12, 0), start, end) is False


def test_time_window_crossing_midnight():
    start, end = time(23, 0), time(2, 0)
    assert in_time_window(time(23, 30), start, end) is True
    assert in_time_window(time(1, 0), start, end) is True
    assert in_time_window(time(2, 0), start, end) is False
    assert in_time_window(time(12, 0), start, end) is False


# ---------- masking ----------
def test_email_is_masked():
    assert mask_text("Contact asha.k@example.com now") == "Contact [EMAIL] now"


@pytest.mark.parametrize("phone", ["+91 98765 43210", "9876543210", "+91-98765-43210"])
def test_phone_is_masked(phone):
    assert mask_text(f"Call {phone} please") == "Call [PHONE] please"


@pytest.mark.parametrize("card", ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"])
def test_card_is_masked(card):
    assert mask_text(f"Card {card} used") == "Card [CARD] used"


def test_api_key_is_masked():
    fake_key = "AIza" + "a" * 35
    assert mask_text(f"key={fake_key}") == "key=[API_KEY]"


def test_normal_text_dates_and_order_ids_are_left_alone():
    text = "Order ORD-1234567890 placed on 2026-11-10 14:30, refund of 500 rupees."
    assert mask_text(text) == text


def test_logger_never_writes_sensitive_data():
    stream = io.StringIO()
    logger = get_logger("masking_test", stream=stream)
    logger.info("User %s paid with %s", "asha@example.com", "4111 1111 1111 1111")
    logger.error("Phone 9876543210 failed")
    output = stream.getvalue()
    assert "asha@example.com" not in output
    assert "4111" not in output
    assert "9876543210" not in output
    assert "[EMAIL]" in output and "[CARD]" in output and "[PHONE]" in output