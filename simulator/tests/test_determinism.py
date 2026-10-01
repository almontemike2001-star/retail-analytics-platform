from beanflow_sim.randomness import hash_uniform
from conftest import build_world


def test_same_seed_same_output(world):
    again = build_world()
    assert again.md.stores == world.md.stores
    assert again.md.products == world.md.products
    assert again.md.customers == world.md.customers
    assert again.orders == world.orders
    assert again.items == world.items
    assert again.payments == world.payments


def test_different_seed_different_output(world):
    other = build_world(seed=8, n_days=2)
    assert [o.order_ts for o in other.orders[:50]] != [o.order_ts for o in world.orders[:50]]


def test_day_is_independent_of_run_length(world):
    """A day generated in a 2-day run equals the same day in a 14-day run (per-day seeding)."""
    short = build_world(n_days=2)
    assert short.batches[1].orders[0][1:] == world.batches[1].orders[0][1:]   # same apart from id


def test_hash_uniform_is_stable_and_bounded():
    a = hash_uniform([1, 2, 3, 10_000], 42, "x")
    assert (a == hash_uniform([1, 2, 3, 10_000], 42, "x")).all()
    assert ((a > 0) & (a < 1)).all()
    assert not (a == hash_uniform([1, 2, 3, 10_000], 43, "x")).all()
