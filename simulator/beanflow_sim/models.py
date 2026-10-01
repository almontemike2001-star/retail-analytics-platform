"""Row types for the 10 source tables.

Fields are in the exact column order of source_db/init/01_schema.sql so rows can
be streamed straight into COPY. Money fields ending in ``_c`` are integer
centavos (exact arithmetic); the db layer converts them to NUMERIC(12,2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import NamedTuple


class RegionRow(NamedTuple):
    region_id: int
    region_name: str


class AreaRow(NamedTuple):
    area_id: int
    region_id: int
    area_name: str


class StoreRow(NamedTuple):
    store_id: int
    area_id: int
    store_code: str
    store_name: str
    store_type: str
    city: str
    latitude: float | None
    longitude: float | None
    opened_date: date
    closed_date: date | None
    status: str
    updated_at: datetime


class CategoryRow(NamedTuple):
    category_id: int
    category_name: str
    category_group: str


class ProductRow(NamedTuple):
    product_id: int
    category_id: int
    sku: str
    product_name: str
    size: str | None
    base_price_c: int
    unit_cost_c: int
    is_active: bool
    launched_date: date
    updated_at: datetime


class CustomerRow(NamedTuple):
    customer_id: int
    full_name: str
    email: str | None
    phone: str | None
    birth_date: date | None
    gender: str | None
    city: str | None
    signup_date: date
    signup_store_id: int | None
    loyalty_tier: str
    updated_at: datetime


class PromotionRow(NamedTuple):
    promotion_id: int
    promo_code: str
    promo_name: str
    promo_type: str
    discount_value_c: int      # percent promos: 1000 = 10.00 %
    min_order_amount_c: int
    start_date: date
    end_date: date
    updated_at: datetime


class OrderRow(NamedTuple):
    order_id: int
    order_number: str
    store_id: int
    customer_id: int | None
    promotion_id: int | None
    order_ts: datetime
    order_channel: str
    order_status: str
    subtotal_c: int
    discount_amount_c: int
    tax_amount_c: int
    total_amount_c: int
    updated_at: datetime


class OrderItemRow(NamedTuple):
    order_item_id: int
    order_id: int
    product_id: int
    quantity: int
    unit_price_c: int
    line_discount_c: int
    line_total_c: int
    updated_at: datetime


class PaymentRow(NamedTuple):
    payment_id: int
    order_id: int
    payment_method: str
    amount_c: int
    payment_status: str
    paid_at: datetime
    updated_at: datetime


# Table name -> (row type, columns as named in PostgreSQL)
def _cols(row_type) -> tuple[str, ...]:
    return tuple(f[:-2] if f.endswith("_c") else f for f in row_type._fields)


TABLES = {
    "regions": (RegionRow, _cols(RegionRow)),
    "areas": (AreaRow, _cols(AreaRow)),
    "stores": (StoreRow, _cols(StoreRow)),
    "product_categories": (CategoryRow, _cols(CategoryRow)),
    "products": (ProductRow, _cols(ProductRow)),
    "customers": (CustomerRow, _cols(CustomerRow)),
    "promotions": (PromotionRow, _cols(PromotionRow)),
    "orders": (OrderRow, _cols(OrderRow)),
    "order_items": (OrderItemRow, _cols(OrderItemRow)),
    "payments": (PaymentRow, _cols(PaymentRow)),
}
MONEY_FIELD_INDEXES = {
    name: tuple(i for i, f in enumerate(rt._fields) if f.endswith("_c")) for name, (rt, _) in TABLES.items()
}
