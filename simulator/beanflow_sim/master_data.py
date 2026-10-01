"""Master data generation: regions, areas, stores, categories, products, promotions.

Pure functions (no database access) so they can be unit-tested. Ids are
assigned explicitly and deterministically; the db layer re-syncs the identity
sequences after insert.
"""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .config import STORE_TYPES, Profile, local_ts
from .models import AreaRow, CategoryRow, CustomerRow, ProductRow, PromotionRow, RegionRow, StoreRow
from .randomness import hash_normal, master_rng
from .reference_data import (AREAS, CATEGORIES, CATEGORY_BY_KEY, MENU, POPULARITY_EXPONENT, REGION_TYPE_MIX,
                             REGIONS, SIZE_SKU_SUFFIX, STORE_NAME_SUFFIX)

NEW_STORE_COUNT = 5            # stores opening inside the default history window (DEV scale)
STORE_PERF_SIGMA = 0.28        # lognormal spread of store performance (stars vs. laggards)


@dataclass
class MasterData:
    regions: list[RegionRow]
    areas: list[AreaRow]
    stores: list[StoreRow]
    categories: list[CategoryRow]
    products: list[ProductRow]
    promotions: list[PromotionRow]
    customers: list[CustomerRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------
def build_regions() -> list[RegionRow]:
    return [RegionRow(rid, name) for rid, name in REGIONS]


def build_areas() -> list[AreaRow]:
    return [AreaRow(a.area_id, a.region_id, a.name) for a in AREAS]


def build_stores(profile: Profile, seed: int, start_date: date) -> list[StoreRow]:
    rng = master_rng(seed, "stores")
    plan: list[tuple] = []   # (area, region_id)
    for a in AREAS:
        n = max(1, round(a.stores * profile.store_scale))
        plan.extend([a] * n)

    n_stores = len(plan)
    types: list[str] = []
    for i, a in enumerate(plan):
        if i < len(STORE_TYPES):                 # guarantee every store type exists, even at tiny scale
            types.append(STORE_TYPES[(i + a.area_id) % len(STORE_TYPES)])
        else:
            types.append(str(rng.choice(STORE_TYPES, p=REGION_TYPE_MIX[a.region_id])))

    n_new = max(1, round(NEW_STORE_COUNT * profile.store_scale))
    new_idx = set(rng.choice(np.arange(len(STORE_TYPES), n_stores), size=min(n_new, n_stores - len(STORE_TYPES)),
                             replace=False).tolist()) if n_stores > len(STORE_TYPES) else set()

    stores: list[StoreRow] = []
    name_counts: Counter = Counter()
    for i, (a, stype) in enumerate(zip(plan, types)):
        store_id = i + 1
        city, lat, lon = a.cities[int(rng.integers(len(a.cities)))]
        base_name = f"BeanFlow {city} {STORE_NAME_SUFFIX[stype]}"
        name_counts[base_name] += 1
        name = base_name if name_counts[base_name] == 1 else f"{base_name} {name_counts[base_name]}"
        if i in new_idx:
            opened = start_date + timedelta(days=int(rng.integers(10, 80)))
            created = local_ts(opened - timedelta(days=30), 9 * 60)       # row set up a month before opening
        else:
            opened = start_date - timedelta(days=int(rng.integers(200, 365 * 8)))
            created = local_ts(opened, 9 * 60)
        stores.append(StoreRow(
            store_id=store_id, area_id=a.area_id, store_code=f"BF-{store_id:03d}", store_name=name,
            store_type=stype, city=city,
            latitude=round(lat + float(rng.normal(0, 0.012)), 6),
            longitude=round(lon + float(rng.normal(0, 0.012)), 6),
            opened_date=opened, closed_date=None, status="active", updated_at=created))
    return stores


def store_performance(store_ids, seed: int) -> np.ndarray:
    """Latent, stable performance multiplier per store (not stored in the source DB)."""
    return np.exp(STORE_PERF_SIGMA * hash_normal(store_ids, seed, "store_perf"))


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
def build_categories() -> list[CategoryRow]:
    return [CategoryRow(c.category_id, c.name, c.group) for c in CATEGORIES]


def build_products(seed: int, start_date: date) -> list[ProductRow]:
    rng = master_rng(seed, "products")
    rows: list[ProductRow] = []
    per_cat_index: Counter = Counter()
    pid = 0
    for cat_key, name, sizes, launch_offset in MENU:
        cat = CATEGORY_BY_KEY[cat_key]
        per_cat_index[cat_key] += 1
        item_no = per_cat_index[cat_key]
        if launch_offset is None:
            launched = start_date - timedelta(days=int(rng.integers(200, 1500)))
            updated = local_ts(launched, 10 * 60)
        else:
            launched = start_date + timedelta(days=launch_offset)
            updated = local_ts(launched - timedelta(days=7), 10 * 60)
        cost_jitter = float(rng.uniform(0.92, 1.08))
        for size, price_php in sizes.items():
            pid += 1
            sku = f"{cat.sku_prefix}-{item_no:02d}" + (f"-{SIZE_SKU_SUFFIX[size]}" if size else "")
            price_c = price_php * 100
            cost_c = int(round(price_c * cat.cost_ratio * cost_jitter))
            rows.append(ProductRow(pid, cat.category_id, sku, name, size, price_c, cost_c, True, launched, updated))
    return rows


def popularity_rank(product_name: str) -> int:
    """1 = best seller within its category (menu order)."""
    for key in CATEGORY_BY_KEY:
        names = [m[1] for m in MENU if m[0] == key]
        if product_name in names:
            return names.index(product_name) + 1
    return len(MENU)


def popularity_weight(product_name: str) -> float:
    return popularity_rank(product_name) ** (-POPULARITY_EXPONENT)


# ---------------------------------------------------------------------------
# Promotions: a monthly campaign calendar
# ---------------------------------------------------------------------------
# Rule kind is encoded in the promo_code prefix; orders.py applies the POS rules.
PROMO_RULES = {
    "PAYDAY15": "percent", "PAYDAY30": "percent", "HOLIDAY": "percent",
    "MERIENDA": "fixed", "MORNINGPAIR": "bundle", "LUNCHCOMBO": "bundle",
}


def promo_rule(promo_code: str) -> str:
    return promo_code.split("-", 1)[0]


def promotions_for_month(year: int, month: int, first_id: int) -> list[PromotionRow]:
    """Deterministic campaigns for one month; created 14 days before the month starts."""
    last = calendar.monthrange(year, month)[1]
    m_start, m_end = date(year, month, 1), date(year, month, last)
    next_first = m_end + timedelta(days=1)
    created = local_ts(m_start - timedelta(days=14), 10 * 60)
    ym, mon = f"{year}{month:02d}", m_start.strftime("%b %Y")
    specs = [
        (f"PAYDAY15-{ym}", f"Payday Treat 10% Off ({mon}, 15th)", "percent", 1000, 30000,
         date(year, month, 14), date(year, month, 16)),
        (f"PAYDAY30-{ym}", f"Payday Treat 10% Off ({mon}, end of month)", "percent", 1000, 30000,
         date(year, month, last - 1), next_first),
    ]
    if month == 12:
        specs.append((f"HOLIDAY-{ym}", f"Holiday Cheer 15% Off ({mon})", "percent", 1500, 50000, m_start, m_end))
    else:
        specs.append((f"MERIENDA-{ym}", f"Merienda Saver PHP 30 Off ({mon})", "fixed", 3000, 25000,
                      date(year, month, 5), date(year, month, min(25, last))))
    if month % 2 == 1:
        specs.append((f"MORNINGPAIR-{ym}", f"Morning Pair: Hot Coffee + Pastry ({mon})", "bundle", 4000, 0,
                      m_start, m_end))
    else:
        specs.append((f"LUNCHCOMBO-{ym}", f"Lunch Combo: Meal + Cold Drink ({mon})", "bundle", 5000, 0,
                      m_start, m_end))
    return [PromotionRow(first_id + i, code, name, ptype, value, min_c, s, e, created)
            for i, (code, name, ptype, value, min_c, s, e) in enumerate(specs)]


def months_between(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ---------------------------------------------------------------------------
# Everything (except customers, see customers.py)
# ---------------------------------------------------------------------------
def build_master_data(profile: Profile, seed: int, start_date: date) -> MasterData:
    promos: list[PromotionRow] = []
    prev_month_day = start_date.replace(day=1) - timedelta(days=1)
    for y, m in months_between(prev_month_day, start_date):
        promos.extend(promotions_for_month(y, m, first_id=len(promos) + 1))
    return MasterData(
        regions=build_regions(), areas=build_areas(), stores=build_stores(profile, seed, start_date),
        categories=build_categories(), products=build_products(seed, start_date), promotions=promos)
