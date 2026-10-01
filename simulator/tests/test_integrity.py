"""Referential integrity and money reconciliation inside the generated data."""

from collections import defaultdict
from datetime import timedelta

from beanflow_sim.config import BUSINESS_TZ, VAT_RATE_PCT


def test_no_broken_foreign_keys(world):
    md = world.md
    region_ids = {r.region_id for r in md.regions}
    area_ids = {a.area_id for a in md.areas}
    store_ids = {s.store_id for s in md.stores}
    category_ids = {x.category_id for x in md.categories}
    product_ids = {p.product_id for p in md.products}
    customer_ids = {x.customer_id for x in md.customers}
    promo_ids = {p.promotion_id for p in md.promotions}
    order_ids = {o.order_id for o in world.orders}

    assert all(a.region_id in region_ids for a in md.areas)
    assert all(s.area_id in area_ids for s in md.stores)
    assert all(p.category_id in category_ids for p in md.products)
    assert all(x.signup_store_id is None or x.signup_store_id in store_ids for x in md.customers)
    for o in world.orders:
        assert o.store_id in store_ids
        assert o.customer_id is None or o.customer_id in customer_ids
        assert o.promotion_id is None or o.promotion_id in promo_ids
    assert all(i.order_id in order_ids and i.product_id in product_ids for i in world.items)
    assert all(p.order_id in order_ids for p in world.payments)
    assert len(order_ids) == len(world.orders)
    assert len({i.order_item_id for i in world.items}) == len(world.items)
    assert len({p.payment_id for p in world.payments}) == len(world.payments)


def test_every_order_has_lines(world):
    with_lines = {i.order_id for i in world.items}
    assert all(o.order_id in with_lines for o in world.orders)


def test_order_totals_reconcile(world):
    lines = defaultdict(list)
    for i in world.items:
        assert i.line_total_c == i.quantity * i.unit_price_c - i.line_discount_c
        lines[i.order_id].append(i)
    for o in world.orders:
        assert o.subtotal_c == sum(i.line_total_c for i in lines[o.order_id])
        assert o.tax_amount_c == ((o.subtotal_c - o.discount_amount_c) * VAT_RATE_PCT + 50) // 100
        assert o.total_amount_c == o.subtotal_c - o.discount_amount_c + o.tax_amount_c


def test_payments_reconcile(world):
    paid = defaultdict(int)
    for p in world.payments:
        if p.payment_status == "paid":
            paid[p.order_id] += p.amount_c
    for o in world.orders:
        if o.order_status == "completed":
            assert paid[o.order_id] == o.total_amount_c
        else:
            assert paid[o.order_id] == 0


def test_promotions_used_only_when_active(world):
    promos = {p.promotion_id: p for p in world.md.promotions}
    for o in world.orders:
        if o.promotion_id:
            d = o.order_ts.astimezone(BUSINESS_TZ).date()
            assert promos[o.promotion_id].start_date <= d <= promos[o.promotion_id].end_date


def test_orders_only_at_trading_stores(world):
    stores = {s.store_id: s for s in world.md.stores}
    for o in world.orders:
        d = o.order_ts.astimezone(BUSINESS_TZ).date()
        assert stores[o.store_id].opened_date <= d


def test_historical_timestamps(world):
    for b, day in zip(world.batches, world.days):
        for o in b.orders:
            local = o.order_ts.astimezone(BUSINESS_TZ)
            assert local.date() == day
            assert o.order_ts <= o.updated_at <= o.order_ts + timedelta(minutes=10)
    for p in world.payments:
        assert p.updated_at == p.paid_at
