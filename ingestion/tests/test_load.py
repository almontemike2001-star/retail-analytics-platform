"""Load / replay semantics with a mocked BigQuery backend (no PostgreSQL, no GCP)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pytest
from google.cloud import bigquery

from beanflow_ingest import parquet as pqm
from beanflow_ingest.bigquery import build_load_job_config, job_id_prefix, partition_target
from beanflow_ingest.reconcile import extract_status, load_status, passed, read_local
from beanflow_ingest.runner import IngestError, Runner
from beanflow_ingest.schemas import load_schema
from beanflow_ingest.windows import day_bounds
from fakes import FakeBigQuery

UTC = timezone.utc
D = date(2026, 7, 3)


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


def no_tmp_left(runner) -> bool:
    root = runner.cfg.repo_root / "data/.load_tmp"
    return not root.exists() or not any(root.iterdir())          # no files AND no <load_batch_id>/ dirs


def land(runner, table, d, n, batch="ext-inc-20260703-test"):
    """Write a complete landing artifact (as extraction would) without PostgreSQL."""
    t = runner.cfg.table(table)
    s = runner.schema(t)
    rows = [{"region_id": i, "region_name": f"R{i}"} for i in range(1, n + 1)] if table == "regions" else \
        [{"payment_id": i, "order_id": i, "payment_method": "cash", "amount": Decimal("100.00"),
          "payment_status": "paid", "paid_at": datetime(2026, 7, 3, 1, tzinfo=UTC),
          "updated_at": datetime(2026, 7, 3, 1, tzinfo=UTC)} for i in range(1, n + 1)]
    path = runner.cfg.landing_file(table, d)
    tbl = pqm.add_extract_metadata(pa.Table.from_pylist(rows, schema=pa.schema(s.source_arrow_fields())), s,
                                   extract_batch_id=batch, extract_mode=t.mode, extracted_at=datetime(2026, 7, 4, tzinfo=UTC),
                                   source_file=runner.cfg.rel(path) if path.exists() else
                                   path.relative_to(runner.cfg.repo_root).as_posix(), ingestion_date=d)
    pqm.write_landing(path, tbl, s)
    ws, we = day_bounds(d, runner.cfg.tz)
    m = pqm.Manifest(1, table, batch, "run", t.mode, d.isoformat(), ws.isoformat(), we.isoformat(), None, 0, n, n, 0,
                     n, path.relative_to(runner.cfg.repo_root).as_posix(), path.stat().st_size,
                     pqm.sha256_file(path), s.hash, "2026-07-04T00:00:00+00:00", "2026-07-04T00:00:00+00:00",
                     "2026-07-04T00:00:01+00:00", 0.0, "complete")
    pqm.write_manifest(path.parent, m)
    return path, m


@pytest.fixture
def setup(cfg):
    bq = FakeBigQuery()
    r = Runner(cfg, None, bq, now_fn=Clock())
    r.init()
    return r, bq


def test_init_creates_partitioned_clustered_tables(setup):
    r, bq = setup
    assert bq.datasets == {"raw_pos", "dq_audit"}
    assert set(bq.tables) == {f"raw_pos.{t.name}" for t in r.cfg.tables} | {"dq_audit.ingestion_log"}
    assert bq.tables["raw_pos.order_items"].cluster_by == ("order_id", "order_item_id")
    assert bq.tables["raw_pos.payments"].cluster_by == ("order_id", "payment_id")
    assert bq.tables["raw_pos.regions"].cluster_by == ()
    assert all(bq.tables[f"raw_pos.{t.name}"].partition_field == "_ingestion_date" for t in r.cfg.tables)


def test_load_job_configuration():
    cfg = build_load_job_config("WRITE_TRUNCATE", {"table": "orders", "business_date": "20260703"})
    assert cfg.source_format == bigquery.SourceFormat.PARQUET
    assert cfg.write_disposition == "WRITE_TRUNCATE"
    assert cfg.create_disposition == "CREATE_NEVER"
    assert cfg.autodetect is False
    assert "NUMERIC" in cfg.decimal_target_types
    assert cfg.labels["pipeline"] == "beanflow" and cfg.labels["table"] == "orders"
    assert partition_target("raw_pos.orders", D) == "raw_pos.orders$20260703"
    assert job_id_prefix("orders", D) == "beanflow_orders_20260703_"
    with pytest.raises(ValueError):
        build_load_job_config("WRITE_EMPTY", {})


def test_load_targets_partition_with_truncate_and_cleans_up(setup):
    r, bq = setup
    path, m = land(r, "payments", D, 5)
    before = pqm.sha256_file(path)
    (o,) = r.load(D, [r.cfg.table("payments")])
    call = bq.load_calls[-1]
    assert call["destination"] == "raw_pos.payments$20260703"
    assert call["config"].write_disposition == "WRITE_TRUNCATE"
    assert ".load_tmp" in call["path"] and call["columns"][-1] == "_loaded_at"
    assert no_tmp_left(r)                                                        # temp artifact + dir removed
    assert pqm.sha256_file(path) == before                                       # landing unchanged
    assert o.status == "loaded" and o.events[0].bq_loaded_rows == 5
    assert bq.partition_rows("raw_pos.payments") == {D: 5}


def test_replay_preserves_extract_id_and_regenerates_load_id(setup):
    r, bq = setup
    _, m = land(r, "payments", D, 3)
    r.load(D, [r.cfg.table("payments")])
    first_loaded_at = bq.tables["raw_pos.payments"].partitions[D].column("_loaded_at")[0].as_py()
    r.load(D, [r.cfg.table("payments")])
    part = bq.tables["raw_pos.payments"].partitions[D]
    assert part.num_rows == 3                                                    # idempotent: no duplicates
    assert set(part.column("_extract_batch_id").to_pylist()) == {m.extract_batch_id}
    assert part.column("_loaded_at")[0].as_py() > first_loaded_at                # new _loaded_at
    events = [e for e in read_local(r.cfg.abs(r.cfg.audit_local_path)) if e["load_batch_id"]]
    assert [e["status"] for e in events] == ["loaded", "replayed"]
    assert events[0]["extract_batch_id"] == events[1]["extract_batch_id"] == m.extract_batch_id
    assert events[0]["load_batch_id"] != events[1]["load_batch_id"]
    assert all("load_batch_id" not in c for c in part.column_names)              # not stored in Bronze rows
    assert len(bq.audit_rows) == 2                                               # audit through append (load job)


def test_cleanup_on_load_failure(setup):
    r, bq = setup
    path, _ = land(r, "payments", D, 2)
    bq.fail_loads = 1
    with pytest.raises(IngestError, match="simulated BigQuery load failure"):
        r.load(D, [r.cfg.table("payments")])
    assert no_tmp_left(r)
    ev = read_local(r.cfg.abs(r.cfg.audit_local_path))[-1]
    assert ev["status"] == "failed" and ev["bq_loaded_rows"] is None
    assert pqm.read_manifest(path.parent).status == "complete"                   # landing untouched


def test_mismatch_is_reported(setup):
    r, bq = setup
    land(r, "payments", D, 4)
    bq.row_skew = -1
    with pytest.raises(IngestError, match="Load failed"):
        r.load(D, [r.cfg.table("payments")])
    assert read_local(r.cfg.abs(r.cfg.audit_local_path))[-1]["status"] == "mismatch"


def test_tampered_landing_is_never_loaded(setup):
    r, bq = setup
    path, _ = land(r, "payments", D, 2)
    path.chmod(0o644)
    path.write_bytes(path.read_bytes()[:-8] + b"tampered")
    with pytest.raises(IngestError, match="sha256"):
        r.load(D, [r.cfg.table("payments")])
    assert bq.load_calls == []


def test_replay_all_rebuilds_whole_table(setup):
    r, bq = setup
    land(r, "regions", D, 4, "ext-1")
    land(r, "regions", D + timedelta(days=1), 4, "ext-2")
    r.load(D, [r.cfg.table("regions")])
    calls_before = len(bq.load_calls)
    (o,) = r.replay_all([r.cfg.table("regions")])
    assert len(bq.load_calls) == calls_before + 1                                 # ONE combined load job
    assert o.status == "replayed" and bq.load_calls[-1]["destination"] == "raw_pos.regions"
    assert bq.load_calls[-1]["config"].write_disposition == "WRITE_TRUNCATE"
    assert no_tmp_left(r)
    assert bq.partition_rows("raw_pos.regions") == {D: 4, D + timedelta(days=1): 4}   # partitions recreated


def test_replay_all_audit_records_the_real_combined_job_count(setup):
    r, bq = setup
    land(r, "regions", D, 4, "ext-1")
    land(r, "regions", D + timedelta(days=1), 3, "ext-2")
    (o,) = r.replay_all([r.cfg.table("regions")])
    ev = [e for e in read_local(r.cfg.abs(r.cfg.audit_local_path)) if e["run_mode"] == "replay_all"]
    assert len(ev) == 1 and o.events[0].row() == ev[0]                           # one row per table / load job
    e = ev[0]
    assert e["extract_batch_id"] is None                                         # several extraction batches
    assert e["parquet_rows"] == 7                                                # combined landing rows
    assert e["bq_loaded_rows"] == bq.load_calls[-1]["rows"] == 7                 # the job's real output_rows
    assert e["bq_job_id"].startswith("beanflow_regions_all_")
    assert e["status"] == "replayed" and e["file_sha256"] is None
    assert e["parquet_file"] == "data/landing/regions/"
    assert e["business_date"] == (D + timedelta(days=1)).isoformat()             # last business date covered
    assert e["window_start"] < e["window_end"]
    assert bq.audit_rows[-1] == e                                                # same row in dq_audit


def test_replay_all_mismatch_keeps_actual_job_count(setup):
    r, bq = setup
    land(r, "regions", D, 4, "ext-1")
    land(r, "regions", D + timedelta(days=1), 4, "ext-2")
    bq.row_skew = -1                                                             # job reports 7 of 8 rows
    with pytest.raises(IngestError, match="Replay failed"):
        r.replay_all([r.cfg.table("regions")])
    (e,) = [x for x in read_local(r.cfg.abs(r.cfg.audit_local_path)) if x["run_mode"] == "replay_all"]
    assert e["status"] == "mismatch" and e["parquet_rows"] == 8 and e["bq_loaded_rows"] == 7
    assert "8 != bq_loaded_rows 7" in e["error_message"]


def test_dates_covered_by_replay_all_reconcile_and_count_as_loaded(setup):
    r, bq = setup
    land(r, "regions", D, 4, "ext-1")
    land(r, "regions", D + timedelta(days=1), 4, "ext-2")
    r.replay_all([r.cfg.table("regions")])
    res = r.reconcile_local([r.cfg.table("regions")])
    assert len(res) == 2 and all(ok for *_, ok, _ in res)
    assert all("via replay-all" in msg for *_, msg in res)
    (o,) = r.load(D, [r.cfg.table("regions")])                                   # later per-date load = replay
    assert o.status == "replayed"


def test_audit_rules():
    assert extract_status(10, 10) == "extracted" and extract_status(10, 9) == "mismatch"
    assert load_status(5, 5, replay=False) == "loaded" and load_status(5, 5, replay=True) == "replayed"
    assert load_status(5, 4, replay=False) == "mismatch"
    assert passed("loaded") and passed("skipped") and not passed("failed") and not passed("mismatch")


def test_load_without_landing_fails_cleanly(setup):
    r, bq = setup
    with pytest.raises(IngestError, match="no landing artifact"):
        r.load(D, [r.cfg.table("orders")])
    ev = read_local(r.cfg.abs(r.cfg.audit_local_path))[-1]
    assert ev["status"] == "failed" and ev["extract_batch_id"] is None


def test_audit_rows_have_all_required_fields(setup):
    r, bq = setup
    land(r, "payments", D, 1)
    r.load(D, [r.cfg.table("payments")])
    required = {"extract_batch_id", "load_batch_id", "business_date", "table_name", "run_mode", "extract_mode",
                "window_start", "window_end", "extract_lower", "lookback_minutes", "source_rows", "rows_in_window",
                "rows_in_lookback", "parquet_rows", "bq_loaded_rows", "parquet_file", "file_sha256", "schema_hash",
                "bq_job_id", "status", "error_message", "started_at", "finished_at", "duration_s"}
    assert set(bq.audit_rows[-1]) == required
