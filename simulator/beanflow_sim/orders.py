"""Daily transaction generation: orders, order_items, payments.

``generate_day`` is pure: given the master-data state valid on a business day,
it returns every order, line and payment for that day. Sampling is vectorised
with NumPy; only the final per-order assembly (promotions, totals, tenders)
loops in Python.

Order of operations for one day
    1. trading stores and expected traffic per store (patterns.py multipliers)
    2. order timestamps from the store type's intraday curve
    3. channel, basket size, walk-in vs. loyalty customer
    4. basket lines: category by daypart and basket position, product by popularity and size preference
    5. promotions, totals (lines -> subtotal -> discount -> VAT -> total), status
    6. payments: tender mix, occasional split tender or failed attempt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .config import PAYMENT_METHODS, Profile, VAT_RATE_PCT, local_ts
from .customers import CustomerPool
from .master_data import popularity_weight, promo_rule, store_performance
from .models import OrderItemRow, OrderRow, PaymentRow, ProductRow, PromotionRow, StoreRow
from .patterns import (CANCEL_RATE, CANCELLED_WITH_FAILED_PAYMENT, DELIVERY_TENDER_PROBS, FAILED_ATTEMPT_RATE,
                       PROMO_USE_RATE, SPLIT_TENDER_RATE, STORE_TYPE_BEHAVIOR, category_cdf, day_multiplier,
                       daypart_of_minute, is_weekend, minute_weights)
from .randomness import day_rng
from .reference_data import CATEGORY_KEYS, REGION_TRAFFIC

CHANNELS = ("dine_in", "takeaway", "delivery")
SIZES = ("small", "medium", "large")
EXTRA_UNIT_RATE = 0.04        # a line occasionally has one extra unit (buying for a friend)


@dataclass
class DayContext:
    """Master-data state valid on the business day being generated."""
    stores: list[StoreRow]
    region_of_area: dict[int, int]
    products: list[ProductRow]
    category_key_of: dict[int, str]           # category_id -> category key
    promotions: list[PromotionRow]
    profile: Profile


@dataclass
class DayBatch:
    orders: list[OrderRow] = field(default_factory=list)
    items: list[OrderItemRow] = field(default_factory=list)
    payments: list[PaymentRow] = field(default_factory=list)


@dataclass
class IdStart:
    order_id: int
    order_item_id: int
    payment_id: int


def trading_stores(stores: list[StoreRow], day: date) -> list[StoreRow]:
    return [s for s in stores
            if s.status == "active" and s.opened_date <= day and (s.closed_date is None or day <= s.closed_date)]


def sellable_products(products: list[ProductRow], day: date) -> list[ProductRow]:
    return [p for p in products if p.is_active and p.launched_date <= day]


def _pick(cdf: np.ndarray, u: np.ndarray) -> np.ndarray:
    return np.minimum(np.searchsorted(cdf, u, side="right"), cdf.size - 1)


def _product_cdfs(products: list[ProductRow], ctx: DayContext) -> dict[tuple[str, int], tuple[np.ndarray, np.ndarray]]:
    """(store_type, category_index) -> (product indexes, cumulative probability)."""
    out = {}
    cat_idx = np.array([CATEGORY_KEYS.index(ctx.category_key_of[p.category_id]) for p in products])
    pop = np.array([popularity_weight(p.product_name) for p in products])
    for stype, beh in STORE_TYPE_BEHAVIOR.items():
        size_w = np.array([1.0 if p.size is None else beh.size_probs[SIZES.index(p.size)] for p in products])
        w = pop * size_w
        for c in range(len(CATEGORY_KEYS)):
            idx = np.flatnonzero(cat_idx == c)
            if idx.size:
                out[(stype, c)] = (idx, np.cumsum(w[idx]) / w[idx].sum())
    return out


def _promo_discount(rule: str, promo: PromotionRow, minute: int, subtotal_c: int,
                    line_cats: list[str], line_gross: list[int]) -> tuple[int, int | None, int]:
    """Return (order-level discount, line index receiving a line discount, line discount)."""
    if rule in ("PAYDAY15", "PAYDAY30", "HOLIDAY"):
        if subtotal_c >= promo.min_order_amount_c:
            return (subtotal_c * promo.discount_value_c // 100 + 50) // 100, None, 0
    elif rule == "MERIENDA":                                   # afternoon only
        if 14 * 60 <= minute < 18 * 60 and subtotal_c >= promo.min_order_amount_c:
            return min(promo.discount_value_c, subtotal_c), None, 0
    elif rule == "MORNINGPAIR":                                # before 11:00, hot coffee + pastry
        if minute < 11 * 60 and "espresso" in line_cats and "pastry" in line_cats:
            li = line_cats.index("pastry")
            return 0, li, min(promo.discount_value_c, line_gross[li])
    elif rule == "LUNCHCOMBO":                                 # 11:00-13:59, meal + cold drink
        if 11 * 60 <= minute < 14 * 60 and "meal" in line_cats and ("iced_coffee" in line_cats or "tea" in line_cats):
            li = line_cats.index("meal")
            return 0, li, min(promo.discount_value_c, line_gross[li])
    return 0, None, 0


def generate_day(day: date, ctx: DayContext, pool: CustomerPool, seed: int, ids: IdStart) -> DayBatch:
    rng = day_rng(seed, day, "orders")
    batch = DayBatch()
    stores = trading_stores(ctx.stores, day)
    products = sellable_products(ctx.products, day)
    if not stores or not products:
        return batch
    promos = [p for p in ctx.promotions if p.start_date <= day <= p.end_date]
    weekend = is_weekend(day)

    # 1-2. traffic per store and order timestamps --------------------------------------------
    store_ids = np.array([s.store_id for s in stores])
    perf = store_performance(store_ids, seed)
    lam = np.array([STORE_TYPE_BEHAVIOR[s.store_type].base_orders * day_multiplier(day, s.store_type)
                    * REGION_TRAFFIC[ctx.region_of_area[s.area_id]] for s in stores]) * perf * ctx.profile.traffic_scale
    counts = rng.poisson(lam)
    o_store = np.repeat(np.arange(len(stores)), counts)
    n = o_store.size
    if n == 0:
        return batch
    o_minute = np.empty(n, dtype=np.int64)
    for si, s in enumerate(stores):
        mask = o_store == si
        if mask.any():
            o_minute[mask] = _pick(np.cumsum(minute_weights(s.store_type, weekend)), rng.random(mask.sum()))
    o_second = rng.integers(0, 60, size=n)
    order = np.lexsort((o_second, o_minute))                    # chronological order ids
    o_store, o_minute, o_second = o_store[order], o_minute[order], o_second[order]
    o_type = np.array([stores[i].store_type for i in o_store])

    # 3. channel, basket size, customers --------------------------------------------------------
    o_channel = np.empty(n, dtype=np.int64)
    o_basket = np.empty(n, dtype=np.int64)
    walk_in = np.empty(n, dtype=bool)
    for stype, beh in STORE_TYPE_BEHAVIOR.items():
        m = o_type == stype
        k = int(m.sum())
        if k:
            o_channel[m] = _pick(np.cumsum(beh.channel_probs), rng.random(k))
            o_basket[m] = _pick(np.cumsum(beh.basket_probs), rng.random(k)) + 1
            walk_in[m] = rng.random(k) < beh.walk_in_share
    o_method = np.empty(n, dtype=np.int64)
    u = rng.random(n)
    for stype, beh in STORE_TYPE_BEHAVIOR.items():
        for ch in range(len(CHANNELS)):
            m = (o_type == stype) & (o_channel == ch)
            if m.any():
                probs = DELIVERY_TENDER_PROBS if CHANNELS[ch] == "delivery" else beh.tender_probs
                o_method[m] = _pick(np.cumsum(probs), u[m])
    o_customer = np.zeros(n, dtype=np.int64)
    reg = np.flatnonzero(~walk_in)
    o_customer[reg] = pool.sample(rng, day, store_ids[o_store[reg]])

    # 4. basket lines ---------------------------------------------------------------------------
    l_order = np.repeat(np.arange(n), o_basket)
    starts = np.cumsum(o_basket) - o_basket
    l_role = (np.arange(l_order.size) != starts[l_order]).astype(np.int64)   # 0 = first item, 1 = add-on
    l_daypart = daypart_of_minute(o_minute[l_order])
    l_type = o_type[l_order]
    l_cat = np.empty(l_order.size, dtype=np.int64)
    u = rng.random(l_order.size)
    for stype in STORE_TYPE_BEHAVIOR:
        cdf = category_cdf(stype)
        m_type = l_type == stype
        for role in (0, 1):
            for dp in range(4):
                m = m_type & (l_role == role) & (l_daypart == dp)
                if m.any():
                    l_cat[m] = _pick(cdf[role, dp], u[m])
    pcdfs = _product_cdfs(products, ctx)
    l_prod = np.full(l_order.size, -1, dtype=np.int64)
    u = rng.random(l_order.size)
    for (stype, c), (pidx, cdf) in pcdfs.items():
        m = (l_type == stype) & (l_cat == c)
        if m.any():
            l_prod[m] = pidx[_pick(cdf, u[m])]
    # category with no sellable product yet (e.g. pre-launch): fall back to the store's top beverage
    if (l_prod < 0).any():
        l_prod[l_prod < 0] = next(iter(pcdfs.values()))[0][0]
    # same product twice in one basket -> one line with quantity 2+
    key = l_order * 10_000 + l_prod
    uniq, first_pos, qty = np.unique(key, return_index=True, return_counts=True)
    keep = np.sort(first_pos)
    qty_by_key = dict(zip(uniq.tolist(), qty.tolist()))
    line_order = l_order[keep]
    line_prod = l_prod[keep]
    line_qty = np.array([qty_by_key[k] for k in key[keep].tolist()], dtype=np.int64)
    line_qty += (rng.random(line_qty.size) < EXTRA_UNIT_RATE).astype(np.int64)

    # 5-6. per-order assembly -------------------------------------------------------------------
    u_status = rng.random(n)
    u_promo = rng.random(n)
    u_split = rng.random(n)
    u_fail = rng.random(n)
    pay_delay = rng.integers(20, 120, size=n)
    line_bounds = np.searchsorted(line_order, np.arange(n + 1))
    store_seq: dict[int, int] = {}
    ymd = day.strftime("%Y%m%d")
    promo_rules = [(p, promo_rule(p.promo_code)) for p in promos]
    oid, iid, pid = ids.order_id, ids.order_item_id, ids.payment_id
    vat = VAT_RATE_PCT

    for i in range(n):
        store = stores[o_store[i]]
        minute = int(o_minute[i])
        ts = local_ts(day, minute) + timedelta(seconds=int(o_second[i]))
        channel = CHANNELS[o_channel[i]]
        customer_id = int(o_customer[i]) or None
        store_seq[store.store_id] = store_seq.get(store.store_id, 0) + 1

        lo, hi = line_bounds[i], line_bounds[i + 1]
        lines = [(products[line_prod[j]], int(line_qty[j])) for j in range(lo, hi)]
        line_cats = [ctx.category_key_of[p.category_id] for p, _ in lines]
        line_gross = [p.base_price_c * q for p, q in lines]
        line_disc = [0] * len(lines)
        subtotal = sum(line_gross)

        promotion_id, order_disc = None, 0
        if promo_rules and u_promo[i] < PROMO_USE_RATE["walk_in" if customer_id is None else "registered"]:
            best = (0, None, None, 0)
            for promo, rule in promo_rules:
                od, li, ld = _promo_discount(rule, promo, minute, subtotal, line_cats, line_gross)
                if od + ld > best[0]:
                    best = (od + ld, promo, li, ld if li is not None else 0)
            if best[1] is not None:
                promotion_id = best[1].promotion_id
                if best[2] is not None:
                    line_disc[best[2]] = best[3]
                    subtotal -= best[3]
                else:
                    order_disc = best[0]
        tax = ((subtotal - order_disc) * vat + 50) // 100
        total = subtotal - order_disc + tax

        cancelled = u_status[i] < CANCEL_RATE[channel]
        status = "cancelled" if cancelled else "completed"
        paid_at = ts + timedelta(seconds=int(pay_delay[i]))
        updated = paid_at + timedelta(seconds=1) if not cancelled else ts + timedelta(minutes=3)
        batch.orders.append(OrderRow(oid, f"{store.store_code}-{ymd}-{store_seq[store.store_id]:04d}",
                                     store.store_id, customer_id, promotion_id, ts, channel, status,
                                     subtotal, order_disc, tax, total, updated))
        for (p, q), gross, ld in zip(lines, line_gross, line_disc):
            batch.items.append(OrderItemRow(iid, oid, p.product_id, q, p.base_price_c, ld, gross - ld, ts))
            iid += 1

        method = PAYMENT_METHODS[o_method[i]]
        if cancelled:
            if u_fail[i] < CANCELLED_WITH_FAILED_PAYMENT and method != "cash":
                batch.payments.append(PaymentRow(pid, oid, method, total, "failed", paid_at, paid_at))
                pid += 1
        else:
            if method != "cash" and u_fail[i] < FAILED_ATTEMPT_RATE:          # declined, then paid in cash
                failed_at = paid_at - timedelta(seconds=15)
                batch.payments.append(PaymentRow(pid, oid, method, total, "failed", failed_at, failed_at))
                pid += 1
                method = "cash"
            if total >= 30_000 and u_split[i] < SPLIT_TENDER_RATE:            # split tender
                first_part = max(5_000, (total // 2) // 5_000 * 5_000)       # round PHP 50s
                second = "cash" if method != "cash" else "e_wallet"
                batch.payments.append(PaymentRow(pid, oid, method, first_part, "paid", paid_at, paid_at))
                batch.payments.append(PaymentRow(pid + 1, oid, second, total - first_part, "paid",
                                                 paid_at + timedelta(seconds=10), paid_at + timedelta(seconds=10)))
                pid += 2
            else:
                batch.payments.append(PaymentRow(pid, oid, method, total, "paid", paid_at, paid_at))
                pid += 1
        oid += 1
    return batch
