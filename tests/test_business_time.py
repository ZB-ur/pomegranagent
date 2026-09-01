"""Focused contracts for the injected Shanghai business clock."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest


def test_business_date_rolls_at_shanghai_midnight() -> None:
    from app.backend.business_time import BusinessClock

    before = BusinessClock(
        "Asia/Shanghai",
        now=lambda: datetime(2026, 9, 1, 15, 59, tzinfo=UTC),
    )
    after = BusinessClock(
        "Asia/Shanghai",
        now=lambda: datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )

    assert before.business_today() == date(2026, 9, 1)
    assert after.business_today() == date(2026, 9, 2)
    assert after.business_now().isoformat() == "2026-09-02T00:00:00+08:00"


def test_week_window_is_monday_inclusive_and_next_monday_exclusive() -> None:
    from app.backend.business_time import BusinessClock

    clock = BusinessClock(
        "Asia/Shanghai",
        now=lambda: datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )

    assert clock.week_window() == (date(2026, 8, 31), date(2026, 9, 7))


def test_explicit_week_anchor_does_not_read_the_provider() -> None:
    from app.backend.business_time import BusinessClock

    def unexpected_now() -> datetime:
        raise AssertionError("explicit anchor must not consult now")

    clock = BusinessClock("Asia/Shanghai", now=unexpected_now)

    assert clock.week_window(date(2026, 9, 6)) == (
        date(2026, 8, 31),
        date(2026, 9, 7),
    )


@pytest.mark.parametrize(
    "invalid_now",
    [
        datetime(2026, 9, 1, 16, 0),
        datetime(2026, 9, 2, 0, 0, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_clock_rejects_naive_or_non_utc_provider_values(invalid_now: datetime) -> None:
    from app.backend.business_time import BusinessClock

    clock = BusinessClock("Asia/Shanghai", now=lambda: invalid_now)

    with pytest.raises(ValueError, match="aware UTC"):
        clock.utc_now()


def test_business_today_reads_the_provider_exactly_once() -> None:
    from app.backend.business_time import BusinessClock

    calls = 0

    def frozen_now() -> datetime:
        nonlocal calls
        calls += 1
        return datetime(2026, 9, 1, 16, 0, tzinfo=UTC)

    clock = BusinessClock("Asia/Shanghai", now=frozen_now)

    assert clock.business_today() == date(2026, 9, 2)
    assert calls == 1
