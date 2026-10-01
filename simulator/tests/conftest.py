"""Small in-memory fixtures (no database required).

Uses the `test` profile (~13 stores, 600 customers) and generates 14 business
days in memory - enough for distribution checks, small enough to run in seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from beanflow_sim.config import get_profile
from beanflow_sim.customers import CustomerPool, build_base_customers
from beanflow_sim.master_data import MasterData, build_master_data, months_between, promotions_for_month
from beanflow_sim.orders import DayBatch, DayContext, IdStart, generate_day
from beanflow_sim.reference_data import CATEGORIES

SEED = 7
START = date(2026, 3, 2)      # a Monday; window includes the 15th payday and the end of March
N_DAYS = 14


@dataclass
class World:
    md: MasterData
    ctx: DayContext
    days: list[date]
    batches: list[DayBatch]

    @property
    def orders(self):
        return [o for b in self.batches for o in b.orders]

    @property
    def items(self):
        return [i for b in self.batches for i in b.items]

    @property
    def payments(self):
        return [p for b in self.batches for p in b.payments]


def build_world(seed: int = SEED, start: date = START, n_days: int = N_DAYS) -> World:
    profile = get_profile("test")
    md = build_master_data(profile, seed, start)
    md.customers = build_base_customers(profile, seed, start, md.stores)
    end = start + timedelta(days=n_days)
    promos = list(md.promotions)
    have = {p.promo_code for p in promos}
    for y, m in months_between(start, end):
        for p in promotions_for_month(y, m, first_id=len(promos) + 1):
            if p.promo_code not in have:
                promos.append(p._replace(promotion_id=len(promos) + 1))
                have.add(p.promo_code)
    md.promotions = promos
    key_by_name = {c.name: c.key for c in CATEGORIES}
    ctx = DayContext(stores=md.stores, region_of_area={a.area_id: a.region_id for a in md.areas},
                     products=md.products, category_key_of={c.category_id: key_by_name[c.category_name]
                                                            for c in md.categories},
                     promotions=promos, profile=profile)
    pool = CustomerPool(seed)
    pool.add_rows(md.customers)
    ids = IdStart(1, 1, 1)
    days, batches = [], []
    for i in range(n_days):
        day = start + timedelta(days=i)
        b = generate_day(day, ctx, pool, seed, ids)
        ids = IdStart(ids.order_id + len(b.orders), ids.order_item_id + len(b.items), ids.payment_id + len(b.payments))
        days.append(day)
        batches.append(b)
    return World(md, ctx, days, batches)


@pytest.fixture(scope="session")
def world() -> World:
    return build_world()
