"""End-to-end extraction against real PostgreSQL + the real simulator (BigQuery mocked).

Uses a DEDICATED database `beanflow_ingest_test` (dropped and recreated); the `beanflow` database is
never touched. Skipped automatically when PostgreSQL or beanflow_sim is unavailable.

Flow (the approved day-by-day order):
    seed -> bootstrap D0-1 -> [simulate D -> ingest D] for 3 days
with two controlled source changes so the assertions are deterministic:
    * one day-1 order gets a late change at D1 23:30 (inside D2's 60-minute lookback)
    * one day-1 order is refunded on D2 (a new version with a later updated_at)
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pyarrow.parquet as pq
import pytest

from beanflow_ingest import parquet as pqm
from beanflow_ingest.config import PgSettings, load_config, load_env_file
from beanflow_ingest.parquet import LandingError
from beanflow_ingest.runner import Runner
from beanflow_ingest.windows import WindowNotClosedError
from conftest import REPO_ROOT, make_repo
from fakes import FakeBigQuery, versions

pytestmark = pytest.mark.integration

MNL = ZoneInfo("Asia/Manila")
TEST_DB = "beanflow_ingest_test"
START = date(2026, 3, 2)
DAYS = [START, START + timedelta(days=1), START + timedelta(days=2)]
SEED = 42

sim = pytest.importorskip("beanflow_sim.runner", reason="beanflow_sim (simulator) not installed")
from beanflow_sim import db as simdb                                            # noqa: E402
from beanflow_sim.config import DbSettings, get_profile                         # noqa: E402


def _pg() -> PgSettings:
    load_env_file()
    try:
        s = PgSettings.from_env()
        psycopg.connect(**s.connect_kwargs(), connect_timeout=3).close()
        return s
    except Exception as exc:                                                    # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable: {exc}")


def _init_dir() -> Path:
    d = Path(os.environ.get("BEANFLOW_SOURCE_INIT_DIR", REPO_ROOT / "source_db" / "init"))
    if not (d / "01_schema.sql").is_file():
        pytest.skip(f"source_db/init not found at {d}")
    return d


def _fresh_db(pg: PgSettings) -> None:
    with psycopg.connect(**pg.connect_kwargs(), autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(**pg.connect_kwargs(TEST_DB), autocommit=True) as c:
        for f in sorted(_init_dir().glob("*.sql")):
            c.execute(f.read_text())


def _sim_conn(pg: PgSettings):
    return simdb.connect(DbSettings(pg.host, pg.port, TEST_DB, pg.user, pg.password))


def build_world(tmp: Path) -> dict:
    pg = _pg()
    _fresh_db(pg)
    repo = make_repo(tmp)
    cfg = load_config(repo_root=repo, env={})
    bq = FakeBigQuery()
    runner = Runner(cfg, pg, bq, pg_dbname=TEST_DB)
    runner.init()
    profile = get_profile("test")
    with _sim_conn(pg) as sc:
        sim.run_seed(sc, profile, SEED, START)
    runner.bootstrap(START - timedelta(days=1), list(cfg.tables))
    marks = {}
    for i, d in enumerate(DAYS):
        with _sim_conn(pg) as sc:
            sim.run_days(sc, profile, SEED, [d])
            if i == 0:   # late change on D1 23:30 -> must reappear in D2 through the lookback
                marks["late"] = sc.execute(
                    "UPDATE pos.orders SET updated_at = %s WHERE order_id = (SELECT min(order_id) FROM pos.orders) "
                    "RETURNING order_id, updated_at", (datetime(d.year, d.month, d.day, 23, 30, tzinfo=MNL),)).fetchone()
            if i == 1:   # refund a D1 order on D2 -> second version with a later updated_at
                marks["refund"] = sc.execute(
                    "UPDATE pos.orders SET order_status = 'refunded', updated_at = %s WHERE order_id = "
                    "(SELECT max(order_id) FROM pos.orders WHERE order_ts < %s AND order_status = 'completed') "
                    "RETURNING order_id, updated_at", (datetime(d.year, d.month, d.day, 15, 0, tzinfo=MNL),
                                                        datetime(d.year, d.month, d.day, tzinfo=MNL))).fetchone()
        runner.run(d, list(cfg.tables))
    counts = {(t.name, d): pqm.read_manifest(cfg.landing_dir(t.name, d)).source_rows
              for t in cfg.tables for d in [START - timedelta(days=1), *DAYS]}
    return {"pg": pg, "cfg": cfg, "bq": bq, "runner": runner, "marks": marks, "counts": counts}


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    first = build_world(tmp_path_factory.mktemp("w1"))
    second = build_world(tmp_path_factory.mktemp("w2"))       # same seed, fresh DB: must be identical
    return first, second


@pytest.fixture(scope="module")
def world(worlds):
    return worlds[1]


def landing(world, table, d):
    return pq.read_table(world["cfg"].landing_file(table, d))


def test_deterministic_source_counts(worlds):
    a, b = worlds
    assert a["counts"] == b["counts"]
    assert a["counts"][("orders", DAYS[0])] > 100


def test_bootstrap_captures_seeded_history(world):
    cfg, b = world["cfg"], START - timedelta(days=1)
    m = {t.name: pqm.read_manifest(cfg.landing_dir(t.name, b)) for t in cfg.tables}
    assert m["customers"].extract_mode == "bootstrap" and m["customers"].source_rows == 600
    assert m["orders"].source_rows == 0 and m["regions"].extract_mode == "full"
    assert m["stores"].source_rows >= 10 and m["products"].source_rows >= 80
    assert landing(world, "customers", b).column("_extract_mode").unique().to_pylist() == ["bootstrap"]


def test_static_full_extract(world):
    t = landing(world, "regions", DAYS[0])
    assert t.column("region_id").to_pylist() == [1, 2, 3, 4]
    assert t.column("_extract_mode").unique().to_pylist() == ["full"]
    assert landing(world, "areas", DAYS[0]).num_rows == 12


def test_incremental_extract_matches_manifest_and_window(world):
    cfg = world["cfg"]
    for d in DAYS:
        for name in ("orders", "order_items", "payments", "customers"):
            m = pqm.read_manifest(cfg.landing_dir(name, d))
            assert m.source_rows == m.parquet_rows == m.rows_in_window + m.rows_in_lookback
            assert m.window_start == datetime(d.year, d.month, d.day, tzinfo=MNL).astimezone(ZoneInfo("UTC")).isoformat()
        t = landing(world, "orders", d)
        lo = datetime(d.year, d.month, d.day, tzinfo=MNL) - timedelta(minutes=60)
        hi = datetime(d.year, d.month, d.day, tzinfo=MNL) + timedelta(days=1)
        assert all(lo <= u < hi for u in t.column("updated_at").to_pylist())
        assert t.column("order_id").to_pylist() == sorted(t.column("order_id").to_pylist())


def test_lookback_duplicate_is_the_same_source_version(world):
    oid, ts = world["marks"]["late"]
    d1, d2 = landing(world, "orders", DAYS[0]), landing(world, "orders", DAYS[1])
    v1, v2 = versions(d1, "order_id"), versions(d2, "order_id")
    assert v1[oid] == v2[oid] == [ts]                                     # identity = (pk, updated_at)
    assert pqm.read_manifest(world["cfg"].landing_dir("orders", DAYS[1])).rows_in_lookback >= 1
    bronze = world["bq"].tables["raw_pos.orders"].all_rows()
    rows = [u for k, u in zip(bronze.column("order_id").to_pylist(), bronze.column("updated_at").to_pylist()) if k == oid]
    assert rows == [ts, ts]                                               # Bronze is NOT deduplicated


def test_refund_creates_a_new_version(world):
    oid, ts = world["marks"]["refund"]
    d1, d2 = landing(world, "orders", DAYS[0]), landing(world, "orders", DAYS[1])
    s1 = dict(zip(d1.column("order_id").to_pylist(), d1.column("order_status").to_pylist()))
    s2 = dict(zip(d2.column("order_id").to_pylist(), d2.column("order_status").to_pylist()))
    assert s1[oid] == "completed" and s2[oid] == "refunded"
    assert versions(d1, "order_id")[oid][0] < versions(d2, "order_id")[oid][0] == ts


def test_metadata_columns(world):
    t = landing(world, "orders", DAYS[0])
    m = pqm.read_manifest(world["cfg"].landing_dir("orders", DAYS[0]))
    assert t.column("_extract_batch_id").unique().to_pylist() == [m.extract_batch_id]
    assert t.column("_ingestion_date").unique().to_pylist() == [DAYS[0]]
    assert t.column("_source_file").unique().to_pylist() == ["data/landing/orders/dt=2026-03-02/part-000.parquet"]
    assert "_loaded_at" not in t.column_names
    assert world["bq"].tables["raw_pos.orders"].partitions[DAYS[0]].column_names[-1] == "_loaded_at"


def test_rerun_replays_without_reextracting(world):
    r, cfg, bq, d = world["runner"], world["cfg"], world["bq"], DAYS[2]
    before_sha = {t.name: pqm.read_manifest(cfg.landing_dir(t.name, d)).sha256 for t in cfg.tables}
    before_rows = {t.name: bq.partition_rows(f"raw_pos.{t.name}")[d] for t in cfg.tables}
    out = r.run(d, list(cfg.tables))
    assert {o.status for o in out if not o.events} == {"skipped"}
    loads = [e for o in out for e in o.events if e.load_batch_id]
    assert {e.status for e in loads} == {"replayed"}
    assert {t.name: pqm.read_manifest(cfg.landing_dir(t.name, d)).sha256 for t in cfg.tables} == before_sha
    assert {t.name: bq.partition_rows(f"raw_pos.{t.name}")[d] for t in cfg.tables} == before_rows
    m = pqm.read_manifest(cfg.landing_dir("orders", d))
    assert all(e.extract_batch_id == pqm.read_manifest(cfg.landing_dir(e.table_name, d)).extract_batch_id for e in loads)
    assert m.extract_batch_id in bq.tables["raw_pos.orders"].partitions[d].column("_extract_batch_id").to_pylist()


def test_force_reextract_rules(world):
    r, cfg = world["runner"], world["cfg"]
    with pytest.raises(LandingError, match="most recent extracted date"):
        r.extract(DAYS[0], [cfg.table("orders")], "incremental", "extract", force=True)
    old = pqm.read_manifest(cfg.landing_dir("orders", DAYS[2]))
    r.extract(DAYS[2], [cfg.table("orders")], "incremental", "extract", force=True)
    new = pqm.read_manifest(cfg.landing_dir("orders", DAYS[2]))
    assert new.source_rows == old.source_rows and new.extract_batch_id != old.extract_batch_id


def test_gap_and_closed_window_guards(world):
    r, cfg = world["runner"], world["cfg"]
    with pytest.raises(LandingError, match="no complete landing artifact"):
        r.extract(DAYS[2] + timedelta(days=2), [cfg.table("orders")], "incremental", "extract")
    today = datetime.now(MNL).date()
    with pytest.raises(WindowNotClosedError):
        r.extract(today, [cfg.table("orders")], "incremental", "extract", allow_gap=True)


def test_reconcile_local_and_full(world):
    r, cfg = world["runner"], world["cfg"]
    r.load(DAYS[2], [cfg.table("orders")])                     # reload after the forced re-extract above
    local = r.reconcile_local(list(cfg.tables))
    assert local and all(ok for _, _, ok, _ in local), [x for x in local if not x[2]]
    full = r.reconcile_full(list(cfg.tables))
    assert all(c.ok for c in full), [c for c in full if not c.ok]
    assert {c.table for c in full} == {t.name for t in cfg.tables}
