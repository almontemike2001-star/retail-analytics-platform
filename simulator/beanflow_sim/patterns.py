"""Intentional business patterns.

Every behavioural assumption of the simulator lives here so it can be read,
tuned and tested in one place:

* store-type behaviour (traffic, weekday/weekend, hours, baskets, channels, tenders)
* calendar effects (payday, seasonality, holidays, growth trend)
* intraday demand curves and dayparts
* category mix by daypart and basket position

All factors are moderate multipliers (no absurd jumps).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np

from .reference_data import CATEGORY_KEYS


# ---------------------------------------------------------------------------
# Store-type behaviour
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StoreTypeBehavior:
    base_orders: float                     # mean orders per store-day before multipliers
    dow: tuple[float, ...]                 # Mon..Sun multipliers
    open_min: tuple[int, int]              # (open, close) minutes after local midnight, weekdays
    open_min_weekend: tuple[int, int]
    peaks: tuple[float, float, float, float]          # weights: morning, lunch, afternoon, evening (weekday)
    peaks_weekend: tuple[float, float, float, float]
    walk_in_share: float                   # share of orders without a loyalty customer
    basket_probs: tuple[float, ...]        # P(basket size = 1..6)
    channel_probs: tuple[float, float, float]   # dine_in, takeaway, delivery
    tender_probs: tuple[float, float, float]    # cash, card, e_wallet
    size_probs: tuple[float, float, float]      # small, medium, large preference
    serves_meals: bool = True


STORE_TYPE_BEHAVIOR: dict[str, StoreTypeBehavior] = {
    # Malls: closed early morning, strong afternoons and weekends, bigger baskets.
    "mall": StoreTypeBehavior(
        base_orders=16.0, dow=(0.85, 0.82, 0.85, 0.88, 1.00, 1.35, 1.40),
        open_min=(10 * 60, 21 * 60), open_min_weekend=(10 * 60, 21 * 60 + 30),
        peaks=(0.2, 1.0, 1.2, 1.0), peaks_weekend=(0.2, 1.0, 1.6, 1.2),
        walk_in_share=0.36, basket_probs=(0.45, 0.31, 0.15, 0.05, 0.03, 0.01),
        channel_probs=(0.50, 0.42, 0.08), tender_probs=(0.25, 0.35, 0.40),
        size_probs=(0.15, 0.48, 0.37)),
    # Street stores: steady all week, balanced day.
    "street": StoreTypeBehavior(
        base_orders=13.0, dow=(0.95, 0.95, 0.97, 0.98, 1.05, 1.10, 1.00),
        open_min=(6 * 60 + 30, 22 * 60), open_min_weekend=(7 * 60, 22 * 60),
        peaks=(1.0, 0.9, 0.9, 0.7), peaks_weekend=(0.7, 0.9, 1.15, 0.8),
        walk_in_share=0.38, basket_probs=(0.52, 0.29, 0.12, 0.04, 0.02, 0.01),
        channel_probs=(0.40, 0.45, 0.15), tender_probs=(0.45, 0.15, 0.40),
        size_probs=(0.22, 0.50, 0.28)),
    # Office towers: weekday commuters, strong morning, collapse on weekends.
    "office": StoreTypeBehavior(
        base_orders=15.0, dow=(1.12, 1.12, 1.12, 1.12, 1.08, 0.45, 0.30),
        open_min=(6 * 60, 20 * 60), open_min_weekend=(8 * 60, 17 * 60),
        peaks=(1.6, 1.1, 0.8, 0.2), peaks_weekend=(0.8, 1.0, 0.8, 0.1),
        walk_in_share=0.25, basket_probs=(0.55, 0.28, 0.11, 0.04, 0.015, 0.005),
        channel_probs=(0.20, 0.62, 0.18), tender_probs=(0.20, 0.30, 0.50),
        size_probs=(0.20, 0.50, 0.30)),
    # Drive-thru: early opening, very strong commute peak, takeaway only.
    "drive_thru": StoreTypeBehavior(
        base_orders=15.0, dow=(1.00, 1.00, 1.00, 1.02, 1.08, 1.05, 0.95),
        open_min=(5 * 60 + 30, 23 * 60), open_min_weekend=(6 * 60, 23 * 60),
        peaks=(1.8, 0.8, 0.6, 0.8), peaks_weekend=(1.1, 0.9, 0.8, 0.9),
        walk_in_share=0.40, basket_probs=(0.50, 0.30, 0.13, 0.04, 0.02, 0.01),
        channel_probs=(0.00, 0.92, 0.08), tender_probs=(0.35, 0.25, 0.40),
        size_probs=(0.18, 0.47, 0.35)),
    # Kiosks: highest ticket count, small baskets, small sizes, no meals -> lowest AOV.
    "kiosk": StoreTypeBehavior(
        base_orders=19.0, dow=(1.00, 1.00, 1.00, 1.00, 1.08, 1.12, 1.05),
        open_min=(7 * 60, 21 * 60), open_min_weekend=(8 * 60, 21 * 60),
        peaks=(1.1, 1.0, 1.0, 0.7), peaks_weekend=(0.8, 1.0, 1.2, 0.8),
        walk_in_share=0.45, basket_probs=(0.72, 0.21, 0.05, 0.015, 0.004, 0.001),
        channel_probs=(0.00, 1.00, 0.00), tender_probs=(0.50, 0.10, 0.40),
        size_probs=(0.40, 0.45, 0.15), serves_meals=False),
}

DELIVERY_TENDER_PROBS = (0.05, 0.25, 0.70)   # app orders are mostly e-wallet
CANCEL_RATE = {"dine_in": 0.015, "takeaway": 0.018, "delivery": 0.045}
REFUND_RATE = 0.007                          # share of completed orders refunded 0-3 days later
SPLIT_TENDER_RATE = 0.03                     # completed orders >= PHP 300 paid with two tenders
FAILED_ATTEMPT_RATE = 0.012                  # card/e-wallet declined, then paid another way
CANCELLED_WITH_FAILED_PAYMENT = 0.30


# ---------------------------------------------------------------------------
# Calendar effects
# ---------------------------------------------------------------------------
MONTH_FACTOR = {1: 0.93, 2: 0.95, 3: 0.98, 4: 0.96, 5: 0.97, 6: 0.98,
                7: 0.97, 8: 0.98, 9: 1.02, 10: 1.04, 11: 1.08, 12: 1.22}

# Fixed-date Philippine holidays and festive days (moving holidays are out of scope for v1).
HOLIDAY_FACTOR = {(1, 1): 0.55, (4, 9): 0.85, (5, 1): 0.85, (6, 12): 0.85, (8, 21): 0.9,
                  (11, 1): 0.80, (11, 30): 0.9, (12, 8): 0.95, (12, 24): 0.85,
                  (12, 25): 0.55, (12, 30): 0.9, (12, 31): 0.75}
TREND_BASE_DATE = date(2024, 1, 1)
TREND_PER_YEAR = 0.10   # +10 % per year like-for-like growth


def payday_factor(d: date) -> float:
    """Philippine paydays: the 15th and the last day of the month (+ the day after)."""
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day in (15, last):
        return 1.12
    if d.day in (16, 1):
        return 1.06
    if d.day in (14, last - 1):
        return 1.03
    return 1.0


def season_factor(d: date) -> float:
    return MONTH_FACTOR[d.month]


def is_holiday(d: date) -> bool:
    return (d.month, d.day) in HOLIDAY_FACTOR


def holiday_factor(d: date, store_type: str) -> float:
    f = HOLIDAY_FACTOR.get((d.month, d.day), 1.0)
    if f < 1.0 and store_type == "office":
        f *= 0.5          # offices are empty on holidays
    return f


def trend_factor(d: date) -> float:
    return 1.0 + TREND_PER_YEAR * (d - TREND_BASE_DATE).days / 365.25


def day_multiplier(d: date, store_type: str) -> float:
    b = STORE_TYPE_BEHAVIOR[store_type]
    return (b.dow[d.weekday()] * payday_factor(d) * season_factor(d)
            * holiday_factor(d, store_type) * trend_factor(d))


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


# ---------------------------------------------------------------------------
# Intraday demand
# ---------------------------------------------------------------------------
# Peak centres (hours) and widths; weights come from the store type.
PEAK_CENTRES = (8.0, 12.5, 15.5, 19.0)    # morning commute, lunch, afternoon merienda, evening
PEAK_WIDTHS = (0.9, 0.8, 1.2, 1.3)
BASELINE = 0.12


@lru_cache(maxsize=None)
def minute_weights(store_type: str, weekend: bool) -> np.ndarray:
    """Probability of an order starting in each minute of the local day (sums to 1)."""
    b = STORE_TYPE_BEHAVIOR[store_type]
    open_m, close_m = b.open_min_weekend if weekend else b.open_min
    peaks = b.peaks_weekend if weekend else b.peaks
    hours = np.arange(1440) / 60.0
    w = np.full(1440, BASELINE)
    for weight, centre, width in zip(peaks, PEAK_CENTRES, PEAK_WIDTHS):
        w += weight * np.exp(-0.5 * ((hours - centre) / width) ** 2)
    w[:open_m] = 0.0
    w[close_m:] = 0.0
    ramp = np.clip((np.arange(1440) - open_m) / 30.0, 0.3, 1.0)   # first 30 min ramp up
    w *= ramp
    return w / w.sum()


# Dayparts: 0 morning (<11:00), 1 lunch (11:00-13:59), 2 afternoon (14:00-17:59), 3 evening (>=18:00)
DAYPART_BOUNDS_MIN = (11 * 60, 14 * 60, 18 * 60)
DAYPARTS = ("morning", "lunch", "afternoon", "evening")


def daypart_of_minute(minutes: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.array(DAYPART_BOUNDS_MIN), minutes, side="right")


# ---------------------------------------------------------------------------
# Category mix
# ---------------------------------------------------------------------------
# Base weights for the first item in a basket vs. add-on items.
CATEGORY_WEIGHT_PRIMARY = {"espresso": 0.20, "iced_coffee": 0.24, "signature": 0.12, "frappe": 0.10,
                           "non_coffee": 0.08, "tea": 0.06, "pastry": 0.08, "sandwich": 0.06,
                           "meal": 0.05, "merch": 0.01}
CATEGORY_WEIGHT_ADDON = {"espresso": 0.08, "iced_coffee": 0.10, "signature": 0.05, "frappe": 0.05,
                         "non_coffee": 0.04, "tea": 0.04, "pastry": 0.30, "sandwich": 0.17,
                         "meal": 0.14, "merch": 0.03}
# Daypart multipliers (morning, lunch, afternoon, evening).
CATEGORY_DAYPART = {
    "espresso":    (1.60, 0.90, 0.70, 0.60),   # hot coffee: morning
    "iced_coffee": (1.00, 1.10, 1.30, 1.00),
    "signature":   (0.90, 1.00, 1.20, 1.10),
    "frappe":      (0.30, 0.90, 1.70, 1.40),   # cold blended: afternoon
    "non_coffee":  (0.60, 1.00, 1.30, 1.20),
    "tea":         (0.50, 1.20, 1.40, 1.00),
    "pastry":      (1.50, 0.80, 1.10, 0.70),   # breakfast + merienda
    "sandwich":    (1.30, 1.40, 0.70, 0.60),
    "meal":        (0.50, 2.00, 0.60, 1.20),   # lunch
    "merch":       (1.00, 1.00, 1.00, 1.00),
}


@lru_cache(maxsize=None)
def category_cdf(store_type: str) -> np.ndarray:
    """Cumulative category probabilities, shape (role=2, daypart=4, n_categories)."""
    serves_meals = STORE_TYPE_BEHAVIOR[store_type].serves_meals
    out = np.zeros((2, 4, len(CATEGORY_KEYS)))
    for role, base in enumerate((CATEGORY_WEIGHT_PRIMARY, CATEGORY_WEIGHT_ADDON)):
        for dp in range(4):
            w = np.array([base[k] * CATEGORY_DAYPART[k][dp] for k in CATEGORY_KEYS])
            if not serves_meals:
                w[[CATEGORY_KEYS.index("meal"), CATEGORY_KEYS.index("sandwich")]] = 0.0
            out[role, dp] = np.cumsum(w / w.sum())
    return out


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
PROPENSITY_PARETO_ALPHA = 1.3     # heavy tail: few very loyal customers
PROPENSITY_CAP = 60.0
HOME_STORE_SHARE = 0.80           # registered orders placed at the customer's home store
NEW_MEMBER_BOOST = 2.5            # extra visit propensity right after signup, decays
NEW_MEMBER_DECAY_DAYS = 21.0
PROMO_USE_RATE = {"registered": 0.35, "walk_in": 0.12}

LOYALTY_THRESHOLDS_PHP = (("platinum", 15_000), ("gold", 7_000), ("silver", 2_500))  # 365-day net spend
