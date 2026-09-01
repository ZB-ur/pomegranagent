"""Validated business-calendar time derived from an injected UTC clock."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


class BusinessClock:
    """Translate one aware UTC sample into the configured business calendar."""

    def __init__(
        self,
        timezone_name: str,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.timezone_name = timezone_name
        self._timezone = ZoneInfo(timezone_name)
        self._now = now or (lambda: datetime.now(UTC))

    def utc_now(self) -> datetime:
        """Return one normalized aware UTC value, rejecting ambiguous providers."""
        value = self._now()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("business clock provider must return an aware UTC datetime")
        return value.astimezone(UTC)

    def business_now(self) -> datetime:
        return self.utc_now().astimezone(self._timezone)

    def business_today(self) -> date:
        return self.business_now().date()

    def week_window(self, anchor: date | None = None) -> tuple[date, date]:
        target = self.business_today() if anchor is None else anchor
        week_start = target - timedelta(days=target.weekday())
        return week_start, week_start + timedelta(days=7)
