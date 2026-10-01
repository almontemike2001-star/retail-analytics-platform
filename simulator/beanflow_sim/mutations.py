"""Source-system changes that happen *after* rows are created.

Each business day ends with a deterministic set of mutations, stamped with
historical ``updated_at`` values on that day (the Phase 1 trigger keeps an
explicitly set ``updated_at``). This gives the Phase 3 incremental extractor
and the dbt SCD2 snapshots real changes to capture:

* completed orders refunded 0-3 days after purchase (+ a refund payment row)
* loyalty-tier upgrades when 365-day spend crosses a threshold
* store temporary closures / reopenings (random), permanent closures and area moves (scheduled)
* product list-price increases (monthly menu review) and unit-cost changes
* next month's promotion calendar loaded ahead of time

Mutations change the *current* state; generation must therefore run
chronologically (enforced by runner.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import psycopg

from . import db
from .config import BUSINESS_TZ, local_ts
from .master_data import promotions_for_month, store_performance
from .models import PromotionRow
from .patterns import LOYALTY_THRESHOLDS_PHP, REFUND_RATE
from .randomness import day_rng

REFUND_WINDOW_DAYS = 3
TEMP_CLOSURE_P = 0.02          # per day, whole chain (~2 renovations per 90 days)
TEMP_CLOSURE_DAYS = 7
PERMANENT_CLOSURE_DAY = 25     # 25th of even months: one laggard store closes for good
AREA_MOVE_DAY = 20             # 20th of each month: territory realignment moves one store
PRICE_CHANGE_DAY = 1           # menu price review on the 1st of each month: one beverage category +PHP 5
COST_CHANGE_P = 0.04           # per day: one category's unit cost +3-8 %
BEVERAGE_CATEGORY_NAMES = ("Espresso Classics", "Iced Coffee", "Signature Lattes", "Frappes",
                           "Non-Coffee", "Tea & Refreshers")


@dataclass
class MutationSummary:
    refunds: int = 0
    tier_upgrades: int = 0
    store_events: list[str] = field(default_factory=list)
    price_changes: int = 0
    cost_changes: int = 0
    promotions_added: int = 0


def ensure_promotions(conn: psycopg.Connection, day: date) -> int:
    """Make sure campaigns exist for this month and the month 14 days ahead."""
    added = 0
    for d in (day, day + timedelta(days=14)):
        candidates = promotions_for_month(d.year, d.month, first_id=0)
        existing = db.existing_promo_codes(conn, [p.promo_code for p in candidates])
        missing = [p for p in candidates if p.promo_code not in existing]
        if missing:
            first = db.next_id(conn, "promotions")
            created = min(missing[0].updated_at, local_ts(day, 6 * 60))   # never later than "today"
            rows = [p._replace(promotion_id=first + i, updated_at=created) for i, p in enumerate(missing)]
            db.copy_rows(conn, "promotions", rows)
            added += len(rows)
    if added:
        db.sync_sequences(conn, ["promotions"])
    return added


def apply_refunds(conn, day: date, rng: np.random.Generator) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT o.order_id, o.order_ts, o.total_amount,
                      (SELECT p.payment_method FROM pos.payments p
                        WHERE p.order_id = o.order_id AND p.payment_status = 'paid'
                        ORDER BY p.amount DESC, p.payment_id LIMIT 1)
                 FROM pos.orders o
                WHERE o.order_status = 'completed' AND o.order_ts >= %s AND o.order_ts < %s
                ORDER BY o.order_id""",
            (local_ts(day - timedelta(days=REFUND_WINDOW_DAYS)), local_ts(day + timedelta(days=1))))
        candidates = cur.fetchall()
        if not candidates:
            return 0
        picked = np.flatnonzero(rng.random(len(candidates)) < REFUND_RATE / (REFUND_WINDOW_DAYS + 1))
        minutes = rng.integers(10 * 60, 21 * 60, size=len(candidates))
        day_end = local_ts(day + timedelta(days=1))
        refunds = []
        for k in picked:
            order_id, order_ts, total, method = candidates[k]
            refund_ts = max(local_ts(day, int(minutes[k])), order_ts.astimezone(BUSINESS_TZ) + timedelta(minutes=30))
            if refund_ts >= day_end or method is None:
                continue
            refunds.append((order_id, refund_ts, total, method))
        if not refunds:
            return 0
        cur.executemany("UPDATE pos.orders SET order_status = 'refunded', updated_at = %s WHERE order_id = %s",
                        [(ts, oid) for oid, ts, _, _ in refunds])
        cur.executemany("INSERT INTO pos.payments (order_id, payment_method, amount, payment_status, paid_at, "
                        "updated_at) VALUES (%s, %s, %s, 'refunded', %s, %s)",
                        [(oid, m, total, ts, ts) for oid, ts, total, m in refunds])
        return len(refunds)


def apply_tier_upgrades(conn, day: date) -> int:
    """Upgrade (never downgrade) customers who ordered today and crossed a 365-day spend threshold."""
    case = " ".join(f"WHEN s.spend >= {php} THEN '{tier}'" for tier, php in LOYALTY_THRESHOLDS_PHP)
    rank = "CASE {col} WHEN 'basic' THEN 0 WHEN 'silver' THEN 1 WHEN 'gold' THEN 2 WHEN 'platinum' THEN 3 END"
    with conn.cursor() as cur:
        cur.execute(
            f"""WITH today AS (
                    SELECT DISTINCT customer_id FROM pos.orders
                     WHERE customer_id IS NOT NULL AND order_ts >= %(d0)s AND order_ts < %(d1)s),
                 s AS (
                    SELECT o.customer_id, SUM(o.total_amount - o.tax_amount) AS spend
                      FROM pos.orders o JOIN today t USING (customer_id)
                     WHERE o.order_status = 'completed' AND o.order_ts >= %(y0)s AND o.order_ts < %(d1)s
                     GROUP BY o.customer_id),
                 target AS (
                    SELECT s.customer_id, CASE {case} ELSE 'basic' END AS tier FROM s)
               UPDATE pos.customers c SET loyalty_tier = t.tier, updated_at = %(ts)s
                 FROM target t
                WHERE c.customer_id = t.customer_id
                  AND {rank.format(col='t.tier')} > {rank.format(col='c.loyalty_tier')}""",
            {"d0": local_ts(day), "d1": local_ts(day + timedelta(days=1)),
             "y0": local_ts(day - timedelta(days=364)), "ts": local_ts(day, 23 * 60 + 50)})
        return cur.rowcount


def apply_store_events(conn, day: date, rng: np.random.Generator, seed: int) -> list[str]:
    events: list[str] = []
    stores = db.load_stores(conn)
    region_of_area = db.load_region_of_area(conn)
    with conn.cursor() as cur:
        # Reopen stores whose renovation is over.
        for s in stores:
            if s.status == "temporarily_closed" and (day - s.updated_at.astimezone(BUSINESS_TZ).date()).days >= TEMP_CLOSURE_DAYS:
                cur.execute("UPDATE pos.stores SET status = 'active', updated_at = %s WHERE store_id = %s",
                            (local_ts(day, 22 * 60), s.store_id))
                events.append(f"reopened {s.store_code}")
        mature = [s for s in stores if s.status == "active" and (day - s.opened_date).days > 365]
        if mature and rng.random() < TEMP_CLOSURE_P:
            s = mature[int(rng.integers(len(mature)))]
            cur.execute("UPDATE pos.stores SET status = 'temporarily_closed', updated_at = %s WHERE store_id = %s",
                        (local_ts(day, 22 * 60), s.store_id))
            events.append(f"temporarily closed {s.store_code}")
        old = [s for s in stores if s.status == "active" and (day - s.opened_date).days > 730]
        if old and day.day == PERMANENT_CLOSURE_DAY and day.month % 2 == 0:
            perf = store_performance([s.store_id for s in old], seed)
            weakest = [old[i] for i in np.argsort(perf)[:5]]          # closures hit laggards
            s = weakest[int(rng.integers(len(weakest)))]
            cur.execute("UPDATE pos.stores SET status = 'closed', closed_date = %s, updated_at = %s "
                        "WHERE store_id = %s", (day, local_ts(day, 22 * 60 + 30), s.store_id))
            events.append(f"permanently closed {s.store_code}")
        active = [s for s in stores if s.status == "active"]
        if active and day.day == AREA_MOVE_DAY:
            s = active[int(rng.integers(len(active)))]
            region = region_of_area[s.area_id]
            options = sorted(a for a, r in region_of_area.items() if r == region and a != s.area_id)
            if options:
                new_area = options[int(rng.integers(len(options)))]
                cur.execute("UPDATE pos.stores SET area_id = %s, updated_at = %s WHERE store_id = %s",
                            (new_area, local_ts(day, 23 * 60), s.store_id))
                events.append(f"moved {s.store_code} to area {new_area}")
    return events


def apply_price_and_cost_changes(conn, day: date, rng: np.random.Generator) -> tuple[int, int]:
    """Effective from the next business day (stamped late evening)."""
    price_n = cost_n = 0
    with conn.cursor() as cur:
        cat = BEVERAGE_CATEGORY_NAMES[int(rng.integers(len(BEVERAGE_CATEGORY_NAMES)))]
        if day.day == PRICE_CHANGE_DAY:
            cur.execute("""UPDATE pos.products p SET base_price = p.base_price + 5, updated_at = %s
                             FROM pos.product_categories c
                            WHERE c.category_id = p.category_id AND c.category_name = %s AND p.is_active""",
                        (local_ts(day, 23 * 60 + 30), cat))
            price_n = cur.rowcount
        if rng.random() < COST_CHANGE_P:
            cur.execute("SELECT category_id FROM pos.product_categories ORDER BY category_id")
            cats = [r[0] for r in cur.fetchall()]
            cat_id = cats[int(rng.integers(len(cats)))]
            factor = round(float(rng.uniform(1.03, 1.08)), 4)
            cur.execute("""UPDATE pos.products SET unit_cost = ROUND(unit_cost * %s::numeric, 2), updated_at = %s
                            WHERE category_id = %s AND is_active""",
                        (factor, local_ts(day, 23 * 60 + 45), cat_id))
            cost_n = cur.rowcount
    return price_n, cost_n


def apply_end_of_day(conn, day: date, seed: int) -> MutationSummary:
    rng = day_rng(seed, day, "mutations")
    summary = MutationSummary()
    summary.refunds = apply_refunds(conn, day, rng)
    summary.tier_upgrades = apply_tier_upgrades(conn, day)
    summary.store_events = apply_store_events(conn, day, rng, seed)
    summary.price_changes, summary.cost_changes = apply_price_and_cost_changes(conn, day, rng)
    db.sync_sequences(conn, ["payments"])
    return summary
