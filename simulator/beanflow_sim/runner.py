"""Orchestration of seed / backfill / daily runs, with idempotency rules.

Rules
* ``seed`` runs once: if master data exists it is skipped (no duplicates).
* Each business day is generated in ONE transaction (signups, orders, lines,
  payments, end-of-day mutations): a day is either fully present or absent.
* Days are generated strictly in chronological order without gaps, because
  mutations (prices, store status, tiers) change the state later days use.
  - a day that already has orders is skipped (safe re-runs)
  - a day earlier than the latest generated day is rejected
  - a gap after the latest generated day is rejected (use backfill)
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from . import db, mutations
from .config import Profile
from .customers import CustomerPool, build_base_customers, generate_signups
from .master_data import build_master_data
from .orders import DayContext, IdStart, generate_day
from .reference_data import CATEGORIES

log = logging.getLogger("beanflow_sim")


class GenerationError(RuntimeError):
    """Raised when a requested run would duplicate or break chronology."""


def run_seed(conn, profile: Profile, seed: int, start_date: date) -> bool:
    if db.is_seeded(conn):
        log.info("Master data already present - seed skipped (run `reset --yes` to start over).")
        return False
    t0 = time.perf_counter()
    md = build_master_data(profile, seed, start_date)
    md.customers = build_base_customers(profile, seed, start_date, md.stores)
    with conn.transaction():
        for table, rows in (("regions", md.regions), ("areas", md.areas), ("stores", md.stores),
                            ("product_categories", md.categories), ("products", md.products),
                            ("promotions", md.promotions), ("customers", md.customers)):
            db.copy_rows(conn, table, rows)
        db.sync_sequences(conn)
    log.info("Seeded %d stores, %d products, %d promotions, %d customers (history start %s) in %.1fs",
             len(md.stores), len(md.products), len(md.promotions), len(md.customers), start_date,
             time.perf_counter() - t0)
    return True


def plan_days(conn, first: date, last: date) -> list[date]:
    """Validate chronology and return the days that still need generating."""
    if first > last:
        raise GenerationError(f"start {first} is after end {last}")
    latest = db.last_generated_day(conn)
    if latest is None:
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]
    if last <= latest:
        log.info("All requested days (%s..%s) are already generated (latest: %s) - nothing to do.", first, last, latest)
        return []
    begin = max(first, latest + timedelta(days=1))
    if begin > latest + timedelta(days=1):
        raise GenerationError(f"Gap: latest generated day is {latest}, requested start {first}. "
                              f"Backfill from {latest + timedelta(days=1)} or reset.")
    if first <= latest:
        log.info("Skipping %s..%s (already generated).", first, latest)
    return [begin + timedelta(days=i) for i in range((last - begin).days + 1)]


def run_days(conn, profile: Profile, seed: int, days: list[date]) -> dict[str, int]:
    if not db.is_seeded(conn):
        raise GenerationError("No master data - run `seed` first.")
    pool = CustomerPool(seed)
    pool.add(*db.load_customer_pool_rows(conn))
    region_of_area = db.load_region_of_area(conn)
    cat_names = db.load_category_names(conn)
    key_by_name = {c.name: c.key for c in CATEGORIES}
    category_key_of = {cid: key_by_name[name] for cid, name in cat_names.items()}
    totals = {"orders": 0, "order_items": 0, "payments": 0, "customers": 0}

    for day in days:
        t0 = time.perf_counter()
        if db.day_has_orders(conn, day):
            log.info("%s already has orders - skipped.", day)
            continue
        with conn.transaction():
            promos_added = mutations.ensure_promotions(conn, day)
            stores = db.load_stores(conn)
            signups = generate_signups(day, profile, seed, db.next_id(conn, "customers"), stores)
            db.insert_customers(conn, signups)
            db.sync_sequences(conn, ["customers"])
            ctx = DayContext(stores=stores, region_of_area=region_of_area, products=db.load_products(conn),
                             category_key_of=category_key_of, promotions=db.load_promotions(conn, day, day),
                             profile=profile)
            ids = IdStart(db.next_id(conn, "orders"), db.next_id(conn, "order_items"), db.next_id(conn, "payments"))
            batch = generate_day(day, ctx, pool, seed, ids)
            db.copy_rows(conn, "orders", batch.orders)
            db.copy_rows(conn, "order_items", batch.items)
            db.copy_rows(conn, "payments", batch.payments)
            db.sync_sequences(conn, ["orders", "order_items", "payments"])
            summary = mutations.apply_end_of_day(conn, day, seed)
        pool.add_rows(signups)
        totals["orders"] += len(batch.orders)
        totals["order_items"] += len(batch.items)
        totals["payments"] += len(batch.payments)
        totals["customers"] += len(signups)
        extras = [f"{summary.refunds} refunds", f"{summary.tier_upgrades} tier upgrades"]
        if summary.price_changes:
            extras.append(f"{summary.price_changes} price changes")
        if summary.cost_changes:
            extras.append(f"{summary.cost_changes} cost changes")
        if promos_added:
            extras.append(f"{promos_added} promotions loaded")
        extras.extend(summary.store_events)
        log.info("%s %s: %5d orders, %5d lines, %4d signups | %s (%.2fs)", day, day.strftime("%a"),
                 len(batch.orders), len(batch.items), len(signups), ", ".join(extras), time.perf_counter() - t0)
    return totals
