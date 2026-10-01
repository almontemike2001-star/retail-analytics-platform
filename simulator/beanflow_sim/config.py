"""Runtime configuration: scale profiles, database settings, accepted values.

Database settings come only from environment variables (optionally loaded from
the repository's .env file). Nothing secret or environment-specific is
hard-coded here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Manila")
VAT_RATE_PCT = 12  # menu prices are VAT-exclusive; tax_amount = 12% of (subtotal - discount)
DEFAULT_SEED = 42


def local_ts(d: date, minutes: float = 0.0) -> datetime:
    """Timezone-aware timestamp `minutes` after local (Asia/Manila) midnight of `d`."""
    return datetime(d.year, d.month, d.day, tzinfo=BUSINESS_TZ) + timedelta(minutes=float(minutes))


def today_local() -> date:
    return datetime.now(BUSINESS_TZ).date()

# ---------------------------------------------------------------------------
# Accepted values - MUST mirror source_db/init/02_constraints.sql
# ---------------------------------------------------------------------------
STORE_TYPES = ("mall", "street", "office", "drive_thru", "kiosk")
STORE_STATUSES = ("active", "temporarily_closed", "closed")
CATEGORY_GROUPS = ("beverage", "food", "merchandise")
PRODUCT_SIZES = ("small", "medium", "large")
LOYALTY_TIERS = ("basic", "silver", "gold", "platinum")
GENDERS = ("female", "male", "non_binary", "undisclosed")
PROMO_TYPES = ("percent", "fixed", "bundle")
ORDER_CHANNELS = ("dine_in", "takeaway", "delivery")
ORDER_STATUSES = ("completed", "cancelled", "refunded")
PAYMENT_METHODS = ("cash", "card", "e_wallet")
PAYMENT_STATUSES = ("paid", "failed", "refunded")


# ---------------------------------------------------------------------------
# Scale profiles
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Profile:
    name: str
    store_scale: float      # multiplier on stores per area (1.0 = 120 stores)
    base_customers: int     # loyalty members who signed up before the history start
    daily_signups: float    # mean new loyalty signups per day (whole chain)
    traffic_scale: float    # multiplier on orders per store-day
    history_days: int       # default backfill length


PROFILES: dict[str, Profile] = {
    # DEV: ~120 stores, ~40k customers, ~1.8k orders/day -> ~160k orders in 90 days
    "dev": Profile("dev", store_scale=1.0, base_customers=36_000, daily_signups=40.0,
                   traffic_scale=1.0, history_days=90),
    # TEST: tiny fixture-sized profile for unit tests and quick experiments
    "test": Profile("test", store_scale=0.1, base_customers=600, daily_signups=3.0,
                    traffic_scale=1.0, history_days=7),
    # FULL is intentionally not defined yet (Phase 8, after the DEV validation gate).
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(f"Unknown profile {name!r}; choose from {sorted(PROFILES)}") from None


# ---------------------------------------------------------------------------
# Database settings
# ---------------------------------------------------------------------------
REQUIRED_DB_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")


def load_env_file(path: Path | None = None) -> Path | None:
    """Load KEY=VALUE pairs from a .env file into os.environ (existing vars win).

    If no path is given, look for `.env` in the current directory and its parents.
    Returns the file that was loaded, or None.
    """
    candidates = [path] if path else [d / ".env" for d in (Path.cwd(), *Path.cwd().parents)]
    for candidate in candidates:
        if candidate and candidate.is_file():
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.split(" #", 1)[0].strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)
            return candidate
    return None


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "DbSettings":
        load_env_file(env_file)
        missing = [v for v in REQUIRED_DB_VARS if not os.environ.get(v)]
        if missing:
            raise RuntimeError(
                "Missing database settings: " + ", ".join(missing)
                + ". Set them in .env (see .env.example) or the environment."
            )
        return cls(
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ["POSTGRES_PORT"]),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )

    def connect_kwargs(self) -> dict:
        return {"host": self.host, "port": self.port, "dbname": self.dbname,
                "user": self.user, "password": self.password,
                "application_name": "beanflow-sim"}

    def __repr__(self) -> str:  # never print the password
        return f"DbSettings(host={self.host!r}, port={self.port}, dbname={self.dbname!r}, user={self.user!r})"
