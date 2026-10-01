"""Intentional business patterns are present (calendar, intraday, customers, products, baskets)."""

from collections import Counter, defaultdict
from datetime import date

import numpy as np

from beanflow_sim import patterns as pt
from beanflow_sim.config import BUSINESS_TZ


def local(o):
    return o.order_ts.astimezone(BUSINESS_TZ)


# ---- calendar ---------------------------------------------------------------------------------
def test_payday_factor_is_moderate():
    assert pt.payday_factor(date(2026, 3, 15)) > pt.payday_factor(date(2026, 3, 10)) == 1.0
    assert pt.payday_factor(date(2026, 2, 28)) > 1.0          # last day of a short month
    assert max(pt.payday_factor(date(2026, 3, d)) for d in range(1, 32)) <= 1.15


def test_december_is_peak_month():
    assert pt.season_factor(date(2026, 12, 10)) == max(pt.MONTH_FACTOR.values())
    assert pt.season_factor(date(2026, 12, 10)) > 1.15 > pt.season_factor(date(2026, 7, 10))


def test_holidays_reduce_office_more():
    xmas = date(2026, 12, 25)
    assert pt.holiday_factor(xmas, "office") < pt.holiday_factor(xmas, "mall") < 1.0


def test_store_type_weekday_weekend_behaviour():
    office, mall = pt.STORE_TYPE_BEHAVIOR["office"].dow, pt.STORE_TYPE_BEHAVIOR["mall"].dow
    assert min(office[:5]) > 2 * max(office[5:])              # offices collapse on weekends
    assert min(mall[5:]) > max(mall[:5])                      # malls peak on weekends


# ---- intraday ---------------------------------------------------------------------------------
def test_minute_weights_respect_opening_hours():
    w = pt.minute_weights("mall", False)
    assert abs(w.sum() - 1) < 1e-9
    assert w[: 10 * 60].sum() == 0 and w[21 * 60:].sum() == 0
    assert pt.minute_weights("drive_thru", False)[: 5 * 60 + 30].sum() == 0


def test_drive_thru_morning_peak_beats_evening():
    w = pt.minute_weights("drive_thru", False)
    assert w[7 * 60:9 * 60].sum() > 2 * w[19 * 60:21 * 60].sum()


def test_generated_orders_follow_store_hours(world):
    stores = {s.store_id: s for s in world.md.stores}
    for o in world.orders:
        beh = pt.STORE_TYPE_BEHAVIOR[stores[o.store_id].store_type]
        open_m, close_m = beh.open_min_weekend if local(o).weekday() >= 5 else beh.open_min
        m = local(o).hour * 60 + local(o).minute
        assert open_m <= m < close_m


def test_hourly_profile_has_peaks(world):
    hours = Counter(local(o).hour for o in world.orders)
    assert hours[8] > hours[6] and hours[12] > hours[10] and hours[15] > hours[21]


# ---- customers --------------------------------------------------------------------------------
def test_walk_in_share(world):
    share = np.mean([o.customer_id is None for o in world.orders])
    assert 0.28 <= share <= 0.45


def test_repeat_behaviour_is_skewed(world):
    per_customer = Counter(o.customer_id for o in world.orders if o.customer_id)
    counts = np.array(sorted(per_customer.values(), reverse=True))
    top10 = counts[: max(1, len(counts) // 10)].sum() / counts.sum()
    assert top10 > 0.25                                       # loyal regulars
    assert (counts == 1).mean() > 0.2                         # many one-time customers
    assert counts.max() >= 5


# ---- products & baskets -----------------------------------------------------------------------
def test_product_popularity_is_pareto_like(world):
    units = Counter()
    for i in world.items:
        units[i.product_id] += i.quantity
    ranked = np.array(sorted(units.values(), reverse=True))
    top20 = ranked[: max(1, len(world.md.products) // 5)].sum() / ranked.sum()
    assert top20 > 0.45


def test_category_mix_changes_by_daypart(world):
    cat_of = {p.product_id: world.ctx.category_key_of[p.category_id] for p in world.md.products}
    ts = {o.order_id: local(o).hour for o in world.orders}
    by_part = defaultdict(Counter)
    for i in world.items:
        h = ts[i.order_id]
        part = "morning" if h < 11 else "lunch" if h < 14 else "afternoon" if h < 18 else "evening"
        by_part[part][cat_of[i.product_id]] += i.quantity

    def share(part, cat):
        return by_part[part][cat] / sum(by_part[part].values())

    assert share("morning", "espresso") > share("afternoon", "espresso")
    assert share("afternoon", "frappe") > share("morning", "frappe")
    assert share("lunch", "meal") > share("morning", "meal")


def test_basket_sizes(world):
    lines = Counter(i.order_id for i in world.items)
    sizes = np.array(list(lines.values()))
    assert (sizes <= 3).mean() >= 0.85
    assert (sizes == 1).mean() >= 0.45
    assert sizes.max() <= 6


def test_kiosk_lower_aov_than_mall(world):
    stores = {s.store_id: s.store_type for s in world.md.stores}
    aov = defaultdict(list)
    for o in world.orders:
        aov[stores[o.store_id]].append(o.total_amount_c - o.tax_amount_c)
    assert np.mean(aov["kiosk"]) < np.mean(aov["mall"])


def test_status_mix(world):
    status = Counter(o.order_status for o in world.orders)
    total = sum(status.values())
    assert status["completed"] / total > 0.95
    assert 0.005 < status["cancelled"] / total < 0.05
