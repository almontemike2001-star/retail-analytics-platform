from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from beanflow_ingest.windows import (WindowNotClosedError, bootstrap_window, business_date_from_interval, day_bounds,
                                     ensure_closed, incremental_window)

MNL = ZoneInfo("Asia/Manila")
UTC = timezone.utc


def test_manila_day_in_utc():
    w = incremental_window(date(2026, 7, 3), MNL, 60)
    assert w.start == datetime(2026, 7, 2, 16, 0, tzinfo=UTC)
    assert w.end == datetime(2026, 7, 3, 16, 0, tzinfo=UTC)
    assert w.end - w.start == timedelta(days=1)


def test_lookback_lower_bound():
    w = incremental_window(date(2026, 7, 3), MNL, 60)
    assert w.lower == datetime(2026, 7, 2, 15, 0, tzinfo=UTC)
    assert incremental_window(date(2026, 7, 3), MNL, 0).lower == w.start


def test_consecutive_windows_have_no_gap_or_overlap():
    d = date(2026, 12, 30)
    for _ in range(5):                      # crosses the year boundary
        a, b = day_bounds(d, MNL), day_bounds(d + timedelta(days=1), MNL)
        assert a[1] == b[0]
        d += timedelta(days=1)


def _in(ts, w):
    return w.lower <= ts < w.end


def test_inclusive_start_exclusive_end():
    d1 = incremental_window(date(2026, 7, 3), MNL, 0)
    d2 = incremental_window(date(2026, 7, 4), MNL, 0)
    midnight = datetime(2026, 7, 4, 0, 0, tzinfo=MNL)               # == d1.end == d2.start
    assert not _in(midnight, d1) and _in(midnight, d2)
    assert _in(midnight - timedelta(microseconds=1), d1)


def test_lookback_overlap_only_covers_the_last_hour():
    d2 = incremental_window(date(2026, 7, 4), MNL, 60)
    assert _in(datetime(2026, 7, 3, 23, 30, tzinfo=MNL), d2)        # late change on D-1 seen again on D
    assert not _in(datetime(2026, 7, 3, 22, 59, tzinfo=MNL), d2)


def test_bootstrap_window_is_unbounded_below():
    w = bootstrap_window(date(2026, 7, 2), MNL)
    assert w.lower is None and w.end == datetime(2026, 7, 2, 16, 0, tzinfo=UTC)


def test_closed_window_guard():
    w = incremental_window(date(2026, 7, 3), MNL, 60)
    with pytest.raises(WindowNotClosedError):
        ensure_closed(w, w.end + timedelta(minutes=4, seconds=59), 5)
    ensure_closed(w, w.end + timedelta(minutes=5), 5)
    with pytest.raises(WindowNotClosedError):
        ensure_closed(w, w.start + timedelta(hours=3), 5)            # "today"
    with pytest.raises(ValueError):
        ensure_closed(w, datetime(2026, 8, 1), 5)                    # naive datetime rejected


def test_airflow_interval_mapping():
    s, e = day_bounds(date(2026, 7, 3), MNL)
    assert business_date_from_interval(s, e, MNL) == date(2026, 7, 3)
    with pytest.raises(ValueError):
        business_date_from_interval(s, e + timedelta(hours=1), MNL)
