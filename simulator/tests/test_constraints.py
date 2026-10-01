"""Generated rows respect every Phase 1 constraint (accepted values, ranges, row rules)."""

import re

from beanflow_sim import config as c


def test_store_rules(world):
    codes = [s.store_code for s in world.md.stores]
    assert len(codes) == len(set(codes))
    for s in world.md.stores:
        assert s.store_type in c.STORE_TYPES and s.status in c.STORE_STATUSES
        assert (s.status == "closed") == (s.closed_date is not None)
        assert -90 <= s.latitude <= 90 and -180 <= s.longitude <= 180
        assert s.store_name.strip()
    assert {s.store_type for s in world.md.stores} == set(c.STORE_TYPES)


def test_product_rules(world):
    skus = [p.sku for p in world.md.products]
    assert len(skus) == len(set(skus))
    assert 80 <= len(world.md.products) <= 100
    for p in world.md.products:
        assert p.size is None or p.size in c.PRODUCT_SIZES
        assert p.base_price_c >= 0 and p.unit_cost_c >= 0
    assert {cat.category_group for cat in world.md.categories} <= set(c.CATEGORY_GROUPS)
    assert len(world.md.categories) == 10


def test_customer_rules(world):
    emails = [x.email for x in world.md.customers if x.email]
    assert len(emails) == len(set(emails))
    pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    for x in world.md.customers:
        assert x.loyalty_tier in c.LOYALTY_TIERS
        assert x.gender is None or x.gender in c.GENDERS
        if x.email:
            assert x.email == x.email.lower() and pattern.match(x.email)
            assert x.email.split("@")[1] in ("example.com", "example.net", "example.org")
        if x.birth_date:
            assert x.birth_date.year >= 1900 and x.birth_date < x.signup_date


def test_promotion_rules(world):
    codes = [p.promo_code for p in world.md.promotions]
    assert len(codes) == len(set(codes))
    for p in world.md.promotions:
        assert p.promo_type in c.PROMO_TYPES
        assert p.start_date <= p.end_date
        assert p.discount_value_c > 0 and p.min_order_amount_c >= 0
        if p.promo_type == "percent":
            assert p.discount_value_c <= 100_00
    assert {p.promo_type for p in world.md.promotions} == set(c.PROMO_TYPES)


def test_order_rules(world):
    numbers = [o.order_number for o in world.orders]
    assert len(numbers) == len(set(numbers))
    for o in world.orders:
        assert o.order_channel in c.ORDER_CHANNELS and o.order_status in c.ORDER_STATUSES
        assert min(o.subtotal_c, o.discount_amount_c, o.tax_amount_c, o.total_amount_c) >= 0
        assert o.discount_amount_c <= o.subtotal_c
        assert len(o.order_number) <= 30


def test_item_rules(world):
    for i in world.items:
        assert i.quantity > 0
        assert i.unit_price_c >= 0 and i.line_discount_c >= 0 and i.line_total_c >= 0
        assert i.line_discount_c <= i.quantity * i.unit_price_c


def test_payment_rules(world):
    for p in world.payments:
        assert p.payment_method in c.PAYMENT_METHODS and p.payment_status in c.PAYMENT_STATUSES
        assert p.amount_c > 0
