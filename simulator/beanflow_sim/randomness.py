"""Deterministic randomness.

Two mechanisms make every run reproducible from one integer seed:

* ``day_rng(seed, day, stream)``: an independent NumPy generator per
  (seed, business day, purpose). Generating 2026-10-01 gives the same rows
  whether it runs inside a backfill or as a standalone ``daily`` run.
* ``hash_uniform(ids, seed, salt)``: a stateless hash (splitmix64) that maps an
  entity id to a stable uniform number. Used for latent traits that are not
  stored in the source database, such as a customer's visit propensity or a
  store's performance level.
"""

from __future__ import annotations

import zlib
from datetime import date

import numpy as np

_STREAMS = {"master": 1, "customers": 2, "signups": 3, "orders": 4, "mutations": 5}


def day_rng(seed: int, day: date, stream: str) -> np.random.Generator:
    return np.random.default_rng([seed, day.toordinal(), _STREAMS[stream]])


def master_rng(seed: int, part: str) -> np.random.Generator:
    return np.random.default_rng([seed, _STREAMS["master"], zlib.crc32(part.encode())])


def _splitmix64(x: np.ndarray) -> np.ndarray:
    x = x + np.uint64(0x9E3779B97F4A7C15)
    x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return x ^ (x >> np.uint64(31))


def hash_uniform(ids, seed: int, salt: str) -> np.ndarray:
    """Stable uniform(0, 1) value per id (vectorised)."""
    ids = np.asarray(ids, dtype=np.uint64)
    mix = np.uint64((seed * 0x100000001B3 + zlib.crc32(salt.encode())) & 0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        z = _splitmix64(ids ^ mix)
        z = _splitmix64(z)
    return ((z >> np.uint64(11)).astype(np.float64) + 0.5) * (1.0 / 9007199254740992.0)


def hash_normal(ids, seed: int, salt: str) -> np.ndarray:
    """Stable standard-normal value per id (Box-Muller on two hashed uniforms)."""
    u1 = hash_uniform(ids, seed, salt + ":u1")
    u2 = hash_uniform(ids, seed, salt + ":u2")
    return np.sqrt(-2.0 * np.log(u1)) * np.cos(2.0 * np.pi * u2)
