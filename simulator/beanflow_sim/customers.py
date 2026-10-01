"""Loyalty customers: base members, daily signups, and the visit-propensity pool.

Customer behaviour is driven by a latent *propensity* derived from the
customer_id with a stable hash (so it is never stored in the source DB, yet is
identical on every run). Propensities follow a capped Pareto distribution, which
produces many one-time customers, a middle group of repeat customers and a
small group of highly loyal regulars.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

import numpy as np
from faker import Faker

from .config import GENDERS, Profile, local_ts
from .master_data import store_performance
from .models import CustomerRow, StoreRow
from .patterns import (HOME_STORE_SHARE, NEW_MEMBER_BOOST, NEW_MEMBER_DECAY_DAYS, PROPENSITY_CAP,
                       PROPENSITY_PARETO_ALPHA, STORE_TYPE_BEHAVIOR, season_factor)
from .randomness import day_rng, hash_uniform, master_rng
from .reference_data import AREAS

EMAIL_DOMAINS = ("example.com", "example.net", "example.org")   # reserved domains: never real inboxes
GENDER_PROBS = (0.52, 0.44, 0.01, 0.03)
APP_SIGNUP_SHARE = 0.08          # signed up in the app: no signup store
EMAIL_MISSING = 0.12
PHONE_MISSING = 0.06
BASE_SIGNUP_LOOKBACK_DAYS = 3 * 365


def propensity(customer_ids, seed: int) -> np.ndarray:
    u = hash_uniform(customer_ids, seed, "customer_propensity")
    return np.minimum((1.0 - u) ** (-1.0 / PROPENSITY_PARETO_ALPHA), PROPENSITY_CAP)


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower()) or "member"


def _store_weights(stores: list[StoreRow], on_day: date, seed: int) -> tuple[np.ndarray, np.ndarray]:
    open_ = [s for s in stores if s.opened_date <= on_day and s.status == "active"]
    if not open_:
        open_ = stores
    ids = np.array([s.store_id for s in open_])
    w = store_performance(ids, seed) * np.array([STORE_TYPE_BEHAVIOR[s.store_type].base_orders for s in open_])
    return ids, w / w.sum()


def _make_customers(rng: np.random.Generator, fake: Faker, first_id: int, signup_dates: list[date],
                    stores: list[StoreRow], seed: int) -> list[CustomerRow]:
    n = len(signup_dates)
    if n == 0:
        return []
    store_by_id = {s.store_id: s for s in stores}
    all_cities = [c[0] for a in AREAS for c in a.cities]
    genders = rng.choice(len(GENDERS), size=n, p=GENDER_PROBS)
    ages = np.clip(16 + rng.gamma(2.2, 6.0, size=n), 16, 70)
    signup_minutes = rng.integers(9 * 60, 21 * 60, size=n)
    app_signup = rng.random(n) < APP_SIGNUP_SHARE
    no_email = rng.random(n) < EMAIL_MISSING
    no_phone = rng.random(n) < PHONE_MISSING
    other_city = rng.random(n) < 0.15
    domains = rng.integers(len(EMAIL_DOMAINS), size=n)
    phones = rng.integers(0, 10**9, size=n)

    rows = []
    weights_cache: dict[date, tuple[np.ndarray, np.ndarray]] = {}
    for i in range(n):
        cid = first_id + i
        sd = signup_dates[i]
        gender = GENDERS[genders[i]]
        first = fake.first_name_female() if gender == "female" else fake.first_name_male() \
            if gender == "male" else fake.first_name()
        last = fake.last_name()
        if sd not in weights_cache:
            weights_cache[sd] = _store_weights(stores, sd, seed)
        ids, w = weights_cache[sd]
        home = None if app_signup[i] else int(ids[np.searchsorted(np.cumsum(w), rng.random() * 0.999999)])
        city = store_by_id[home].city if home and not other_city[i] else all_cities[int(rng.integers(len(all_cities)))]
        birth = sd - timedelta(days=int(ages[i] * 365.25) + int(rng.integers(0, 365)))
        rows.append(CustomerRow(
            customer_id=cid, full_name=f"{first} {last}",
            email=None if no_email[i] else f"{_slug(first)}.{_slug(last)}{cid}@{EMAIL_DOMAINS[domains[i]]}",
            phone=None if no_phone[i] else f"09{phones[i]:09d}",
            birth_date=birth, gender=gender, city=city, signup_date=sd, signup_store_id=home,
            loyalty_tier="basic", updated_at=local_ts(sd, int(signup_minutes[i]))))
    return rows


def build_base_customers(profile: Profile, seed: int, start_date: date, stores: list[StoreRow]) -> list[CustomerRow]:
    """Members who signed up during the 3 years before the history start (recent years weighted)."""
    rng = master_rng(seed, "base_customers")
    fake = Faker("en_PH")
    fake.seed_instance(seed)
    n = profile.base_customers
    days_back = 1 + np.floor((BASE_SIGNUP_LOOKBACK_DAYS - 1) * rng.random(n) ** 1.6).astype(int)
    signup_dates = sorted(start_date - timedelta(days=int(d)) for d in days_back)
    rows = _make_customers(rng, fake, 1, signup_dates, stores, seed)

    # Existing members already carry a tier that matches their (latent) loyalty.
    prop = propensity([r.customer_id for r in rows], seed)
    q = np.argsort(np.argsort(-prop)) / max(1, n - 1)     # 0 = most loyal
    out = []
    for r, rank in zip(rows, q):
        tier = "platinum" if rank < 0.01 else "gold" if rank < 0.05 else "silver" if rank < 0.17 else "basic"
        if tier != "basic":
            span = max(1, (start_date - r.signup_date).days - 1)
            upgraded_on = r.signup_date + timedelta(days=int(rng.integers(0, span)))
            r = r._replace(loyalty_tier=tier, updated_at=max(r.updated_at, local_ts(upgraded_on, 23 * 60)))
        out.append(r)
    return out


def generate_signups(day: date, profile: Profile, seed: int, first_id: int, stores: list[StoreRow]) -> list[CustomerRow]:
    """New loyalty members who sign up on `day` (deterministic per day)."""
    rng = day_rng(seed, day, "signups")
    n = int(rng.poisson(profile.daily_signups * season_factor(day)))
    fake = Faker("en_PH")
    fake.seed_instance(seed * 1_000_003 + day.toordinal())
    return _make_customers(rng, fake, first_id, [day] * n, stores, seed)


class CustomerPool:
    """In-memory view of customers used to attach orders to loyalty members."""

    def __init__(self, seed: int):
        self.seed = seed
        self.ids = np.empty(0, dtype=np.int64)
        self.home = np.empty(0, dtype=np.int64)          # 0 = no home store
        self.signup_ord = np.empty(0, dtype=np.int64)
        self.prop = np.empty(0, dtype=np.float64)

    def add(self, ids, home_store_ids, signup_dates) -> None:
        ids = np.asarray(ids, dtype=np.int64)
        if ids.size == 0:
            return
        self.ids = np.concatenate([self.ids, ids])
        self.home = np.concatenate([self.home, np.array([h or 0 for h in home_store_ids], dtype=np.int64)])
        self.signup_ord = np.concatenate([self.signup_ord,
                                          np.array([d.toordinal() for d in signup_dates], dtype=np.int64)])
        self.prop = np.concatenate([self.prop, propensity(ids, self.seed)])

    def add_rows(self, rows: list[CustomerRow]) -> None:
        self.add([r.customer_id for r in rows], [r.signup_store_id for r in rows], [r.signup_date for r in rows])

    def __len__(self) -> int:
        return int(self.ids.size)

    def sample(self, rng: np.random.Generator, day: date, order_store_ids: np.ndarray) -> np.ndarray:
        """Pick one customer per order (orders given by store id). Members are eligible from the day after signup."""
        out = np.zeros(order_store_ids.size, dtype=np.int64)
        if order_store_ids.size == 0:
            return out
        eligible = self.signup_ord < day.toordinal()
        if not eligible.any():
            raise RuntimeError("No eligible customers for this day - run `seed` first.")
        ids, home, prop = self.ids[eligible], self.home[eligible], self.prop[eligible]
        age = day.toordinal() - self.signup_ord[eligible]
        w = prop * (1.0 + NEW_MEMBER_BOOST * np.exp(-age / NEW_MEMBER_DECAY_DAYS))
        global_cdf = np.cumsum(w) / w.sum()

        use_home = rng.random(order_store_ids.size) < HOME_STORE_SHARE
        u = rng.random(order_store_ids.size)
        order_idx = np.argsort(home, kind="stable")
        sorted_home = home[order_idx]
        for store_id in np.unique(order_store_ids):
            at_store = np.flatnonzero(order_store_ids == store_id)
            lo, hi = np.searchsorted(sorted_home, [store_id, store_id + 1])
            home_members = order_idx[lo:hi]
            home_orders = at_store[use_home[at_store]] if home_members.size else np.empty(0, dtype=np.int64)
            if home_orders.size:
                cdf = np.cumsum(w[home_members]) / w[home_members].sum()
                out[home_orders] = ids[home_members[np.searchsorted(cdf, u[home_orders] * 0.999999)]]
            other = np.setdiff1d(at_store, home_orders, assume_unique=True)
            if other.size:
                out[other] = ids[np.searchsorted(global_cdf, u[other] * 0.999999)]
        return out
