from datetime import UTC, date, datetime

import pytest

from utils.dates import today_in_timezone


def test_today_uses_client_timezone() -> None:
    instant = datetime(2026, 8, 8, 2, 0, tzinfo=UTC)
    assert today_in_timezone("America/Chicago", instant) == date(2026, 8, 7)
    assert today_in_timezone("Asia/Karachi", instant) == date(2026, 8, 8)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        today_in_timezone("UTC", datetime(2026, 8, 8))
