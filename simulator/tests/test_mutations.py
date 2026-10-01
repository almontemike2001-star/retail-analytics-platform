"""Source-change timestamps must fall inside the business day they happen on."""

from datetime import date, timedelta

from beanflow_sim.config import local_ts
from beanflow_sim.master_data import promotions_for_month
from beanflow_sim.mutations import stamp_new_promotions


def test_new_promotions_are_stamped_on_the_loading_day():
    # August campaigns first loaded on 2026-07-20, i.e. after "month start - 14 days" (2026-07-18).
    day = date(2026, 7, 20)
    rows = stamp_new_promotions(promotions_for_month(2026, 8, first_id=0), day, first_id=101)
    assert [r.promotion_id for r in rows] == list(range(101, 101 + len(rows)))
    for r in rows:
        assert r.updated_at == local_ts(day, 6 * 60)
        assert local_ts(day) <= r.updated_at < local_ts(day + timedelta(days=1))   # inside window D


def test_promotions_loaded_ahead_are_not_backdated():
    day = date(2026, 7, 18)                       # exactly 14 days before August
    rows = stamp_new_promotions(promotions_for_month(2026, 8, first_id=0), day, first_id=1)
    assert all(r.updated_at.date() == day for r in rows)
