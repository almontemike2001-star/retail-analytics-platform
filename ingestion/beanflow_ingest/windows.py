"""Business-day extraction windows (Asia/Manila) expressed as UTC instants.

    window_start  = D 00:00 Asia/Manila            (inclusive)
    window_end    = (D+1) 00:00 Asia/Manila        (exclusive)
    extract_lower = window_start - lookback        (incremental only)

    incremental predicate:  updated_at >= extract_lower AND updated_at < window_end
    bootstrap predicate:    updated_at < window_end                (mutable tables, as-of date D)
    full predicate:         none                                   (static tables)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc


class WindowNotClosedError(RuntimeError):
    """The requested business day has not been closed long enough to extract safely."""


@dataclass(frozen=True)
class Window:
    business_date: date
    start: datetime          # UTC, inclusive
    end: datetime            # UTC, exclusive
    lower: datetime | None   # UTC, inclusive lower bound actually extracted (None = unbounded)
    lookback_minutes: int

    @property
    def in_lookback(self) -> bool:
        return self.lower is not None and self.lower < self.start


def day_bounds(business_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime(business_date.year, business_date.month, business_date.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)          # Asia/Manila has no DST; still computed tz-aware
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def incremental_window(business_date: date, tz: ZoneInfo, lookback_minutes: int) -> Window:
    start, end = day_bounds(business_date, tz)
    return Window(business_date, start, end, start - timedelta(minutes=lookback_minutes), lookback_minutes)


def bootstrap_window(as_of: date, tz: ZoneInfo) -> Window:
    """Everything that existed by the end of `as_of` (the day before the first simulated day)."""
    start, end = day_bounds(as_of, tz)
    return Window(as_of, start, end, None, 0)


def full_window(business_date: date, tz: ZoneInfo) -> Window:
    start, end = day_bounds(business_date, tz)
    return Window(business_date, start, end, None, 0)


def ensure_closed(window: Window, now: datetime, settle_minutes: int) -> None:
    """Refuse windows whose end is less than `settle_minutes` in the past."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if window.end > now - timedelta(minutes=settle_minutes):
        raise WindowNotClosedError(
            f"Business day {window.business_date} closes at {window.end.isoformat()} UTC; extraction is allowed "
            f"from {(window.end + timedelta(minutes=settle_minutes)).isoformat()} UTC (settle {settle_minutes} min).")


def business_date_from_interval(start: datetime, end: datetime, tz: ZoneInfo) -> date:
    """Map an Airflow data interval to its business date (must be exactly one local day)."""
    local = start.astimezone(tz)
    d = local.date()
    if (start, end) != day_bounds(d, tz):
        raise ValueError(f"Interval {start}..{end} is not exactly one {tz.key} business day")
    return d
