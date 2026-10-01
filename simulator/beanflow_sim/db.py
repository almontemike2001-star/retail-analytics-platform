"""PostgreSQL access: connections, COPY bulk loads, state loading, sequence sync.

Every write path uses COPY (psycopg 3), so a full DEV day of ~2k orders, ~3k
lines and ~2k payments loads in well under a second.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Sequence

import psycopg

from .config import BUSINESS_TZ, DbSettings, local_ts
from .models import MONEY_FIELD_INDEXES, TABLES, CustomerRow, ProductRow, PromotionRow, StoreRow

ALL_TABLES = ("regions", "areas", "stores", "product_categories", "products", "customers",
              "promotions", "orders", "order_items", "payments")
ID_COLUMNS = {"regions": "region_id", "areas": "area_id", "stores": "store_id", "product_categories": "category_id",
              "products": "product_id", "customers": "customer_id", "promotions": "promotion_id",
              "orders": "order_id", "order_items": "order_item_id", "payments": "payment_id"}


def connect(settings: DbSettings) -> psycopg.Connection:
    # autocommit: every `with conn.transaction()` block is a real, independently committed transaction
    conn = psycopg.connect(**settings.connect_kwargs(), autocommit=True)
    conn.execute("SET TIME ZONE 'UTC'")
    return conn


def _money(c: int) -> str:
    if c < 0:
        raise ValueError(f"negative money value {c}")
    return f"{c // 100}.{c % 100:02d}"


def copy_rows(conn: psycopg.Connection, table: str, rows: Sequence[tuple]) -> int:
    """Bulk-load rows (NamedTuples from models.py) into pos.<table> with COPY."""
    if not rows:
        return 0
    _, columns = TABLES[table]
    money_idx = MONEY_FIELD_INDEXES[table]
    sql = f"COPY pos.{table} ({', '.join(columns)}) FROM STDIN"
    with conn.cursor() as cur, cur.copy(sql) as cp:
        for row in rows:
            if money_idx:
                row = list(row)
                for i in money_idx:
                    row[i] = _money(row[i])
            cp.write_row(row)
    return len(rows)


def sync_sequences(conn: psycopg.Connection, tables: Iterable[str] = ALL_TABLES) -> None:
    """Move identity sequences past explicitly inserted ids (required after COPY with ids)."""
    with conn.cursor() as cur:
        for t in tables:
            col = ID_COLUMNS[t]
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('pos.{t}', '{col}'), "
                f"GREATEST((SELECT COALESCE(MAX({col}), 0) FROM pos.{t}), 1), "
                f"(SELECT COUNT(*) > 0 FROM pos.{t}))")


def next_id(conn: psycopg.Connection, table: str) -> int:
    col = ID_COLUMNS[table]
    with conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX({col}), 0) + 1 FROM pos.{table}")
        return int(cur.fetchone()[0])


def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    out = {}
    with conn.cursor() as cur:
        for t in ALL_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM pos.{t}")
            out[t] = int(cur.fetchone()[0])
    return out


def is_seeded(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pos.regions)")
        return bool(cur.fetchone()[0])


def last_generated_day(conn: psycopg.Connection) -> date | None:
    """Latest business day (Asia/Manila) that has orders."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX((order_ts AT TIME ZONE %s)::date) FROM pos.orders", (str(BUSINESS_TZ),))
        return cur.fetchone()[0]


def day_has_orders(conn: psycopg.Connection, day: date) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pos.orders WHERE order_ts >= %s AND order_ts < %s)",
                    (local_ts(day), local_ts(day + timedelta(days=1))))
        return bool(cur.fetchone()[0])


def reset(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(f"pos.{t}" for t in ALL_TABLES) + " RESTART IDENTITY CASCADE")


# ---------------------------------------------------------------------------
# State loading (money columns converted back to integer centavos)
# ---------------------------------------------------------------------------
def load_stores(conn) -> list[StoreRow]:
    with conn.cursor() as cur:
        cur.execute("SELECT store_id, area_id, store_code, store_name, store_type, city, latitude::float8, "
                    "longitude::float8, opened_date, closed_date, status, updated_at FROM pos.stores ORDER BY store_id")
        return [StoreRow(*r) for r in cur.fetchall()]


def load_region_of_area(conn) -> dict[int, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT area_id, region_id FROM pos.areas")
        return dict(cur.fetchall())


def load_category_names(conn) -> dict[int, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT category_id, category_name FROM pos.product_categories")
        return dict(cur.fetchall())


def load_products(conn) -> list[ProductRow]:
    with conn.cursor() as cur:
        cur.execute("SELECT product_id, category_id, sku, product_name, size, (base_price * 100)::bigint, "
                    "(unit_cost * 100)::bigint, is_active, launched_date, updated_at FROM pos.products ORDER BY product_id")
        return [ProductRow(*r) for r in cur.fetchall()]


def load_promotions(conn, first: date, last: date) -> list[PromotionRow]:
    with conn.cursor() as cur:
        cur.execute("SELECT promotion_id, promo_code, promo_name, promo_type, (discount_value * 100)::bigint, "
                    "(min_order_amount * 100)::bigint, start_date, end_date, updated_at FROM pos.promotions "
                    "WHERE start_date <= %s AND end_date >= %s ORDER BY promotion_id", (last, first))
        return [PromotionRow(*r) for r in cur.fetchall()]


def existing_promo_codes(conn, codes: Sequence[str]) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT promo_code FROM pos.promotions WHERE promo_code = ANY(%s)", (list(codes),))
        return {r[0] for r in cur.fetchall()}


def load_customer_pool_rows(conn) -> tuple[list[int], list[int | None], list[date]]:
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id, signup_store_id, signup_date FROM pos.customers ORDER BY customer_id")
        rows = cur.fetchall()
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


def insert_customers(conn, rows: list[CustomerRow]) -> int:
    return copy_rows(conn, "customers", rows)
