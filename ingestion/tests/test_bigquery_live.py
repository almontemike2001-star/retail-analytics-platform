"""OPTIONAL live BigQuery smoke tests - excluded by default.

Run explicitly with your own ADC credentials:
    GCP_PROJECT_ID=<project> pytest -m bigquery
They create throw-away datasets (raw_pos_test_<random>, dq_audit_test_<random>) and delete them afterwards.

BigQuery Sandbox: tables/partitions expire after 60 days, so the LIVE tests use recent, dynamic business dates
(today - 2 days for regions, today - 1 day for payments). Fixed historical dates would load into partitions that
are already past the Sandbox retention. The permanent history stays in the local Parquet landing zone;
BigQuery Bronze is a temporary analytics layer that can always be rebuilt with `load --replay-all`.

The landing manifests are built with the production window helpers (Asia/Manila -> UTC), so every timestamp
that reaches dq_audit.ingestion_log is a real ISO-8601 UTC value. The offline checks at the bottom run in the
default test suite (no BigQuery) and keep the exact, fixed-date timezone assertions.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pyarrow as pa
import pytest

from beanflow_ingest import parquet as pqm
from beanflow_ingest.config import load_config
from beanflow_ingest.reconcile import audit_bq_schema, iso, read_local
from beanflow_ingest.runner import Runner
from beanflow_ingest.windows import Window, full_window, incremental_window

UTC = timezone.utc


@pytest.fixture
def live(repo):
    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        pytest.skip("GCP_PROJECT_ID not set")
    from beanflow_ingest.bigquery import BigQueryClient
    suffix = uuid.uuid4().hex[:8]
    cfg = load_config(repo_root=repo, env={"GCP_PROJECT_ID": project, "BQ_RAW_DATASET": f"raw_pos_test_{suffix}",
                                           "BQ_AUDIT_DATASET": f"dq_audit_test_{suffix}"})
    bq = BigQueryClient(project, cfg.bq_location, cfg.max_query_bytes)
    yield cfg, bq
    for ds in (cfg.bq_raw_dataset, cfg.bq_audit_dataset):
        bq.client.delete_dataset(f"{project}.{ds}", delete_contents=True, not_found_ok=True)


def _window(cfg, table: str, d: date) -> Window:
    """Same window the production extractor would use for this table and business date."""
    t = cfg.table(table)
    return incremental_window(d, cfg.tz, t.lookback_minutes) if t.incremental else full_window(d, cfg.tz)


def _land(cfg, runner, table: str, d: date, rows: list[dict], extract_batch_id: str, run_mode: str) -> pqm.Manifest:
    """Write a permanent landing artifact + manifest exactly as extraction would (real timestamps only)."""
    t = cfg.table(table)
    s = runner.schema(t)
    w = _window(cfg, table, d)
    path = cfg.landing_file(table, d)
    extracted_at = min(w.end + timedelta(hours=2), datetime.now(UTC))   # after the window closed, never in the future
    started_at, finished_at = extracted_at, extracted_at + timedelta(seconds=1)
    tbl = pqm.add_extract_metadata(pa.Table.from_pylist(rows, schema=pa.schema(s.source_arrow_fields())), s,
                                   extract_batch_id=extract_batch_id, extract_mode=t.mode,
                                   extracted_at=extracted_at, source_file=path.relative_to(cfg.repo_root).as_posix(),
                                   ingestion_date=d)
    pqm.write_landing(path, tbl, s)
    n = len(rows)
    m = pqm.Manifest(
        manifest_version=1, table=table, extract_batch_id=extract_batch_id, run_mode=run_mode,
        extract_mode=t.mode, business_date=d.isoformat(),
        window_start=iso(w.start), window_end=iso(w.end), extract_lower=iso(w.lower),
        lookback_minutes=w.lookback_minutes, source_rows=n, rows_in_window=n, rows_in_lookback=0, parquet_rows=n,
        parquet_file=path.relative_to(cfg.repo_root).as_posix(), file_size_bytes=path.stat().st_size,
        sha256=pqm.sha256_file(path), schema_hash=s.hash,
        extracted_at=iso(extracted_at), started_at=iso(started_at), finished_at=iso(finished_at),
        duration_s=1.0, status="complete")
    pqm.write_manifest(path.parent, m)
    return m


SANDBOX_RETENTION_DAYS = 60
REGION_ROWS = [{"region_id": i, "region_name": f"Region {i}"} for i in range(1, 5)]


def regions_live_date() -> date:
    return date.today() - timedelta(days=2)


def payments_live_date() -> date:
    return date.today() - timedelta(days=1)


def payment_ts(cfg, d: date) -> datetime:
    """A microsecond-precision UTC timestamp inside business day d's window (23:59:59.123456 Manila)."""
    return incremental_window(d, cfg.tz, 0).end - timedelta(microseconds=876544)


def payment_rows(ts: datetime) -> list[dict]:
    return [{"payment_id": 1, "order_id": 10, "payment_method": "card", "amount": Decimal("9999999999.99"),
             "payment_status": "paid", "paid_at": ts, "updated_at": ts}]


@pytest.mark.bigquery
def test_live_init_load_replay(live):
    cfg, bq = live
    r = Runner(cfg, None, bq)
    r.init()
    d = regions_live_date()                                           # inside the Sandbox 60-day retention
    t = cfg.table("regions")
    _land(cfg, r, "regions", d, REGION_ROWS, "ext-live", "bootstrap")
    r.load(d, [t])
    r.load(d, [t])                                                    # replay: still 4 rows
    n = bq.query(f"SELECT COUNT(*) AS n FROM `{bq.project}.{cfg.bq_raw_dataset}.regions` "
                 f"WHERE _ingestion_date = '{d.isoformat()}'")[0]["n"]
    assert n == 4
    assert [e["status"] for e in read_local(cfg.abs(cfg.audit_local_path))] == ["loaded", "replayed"]


@pytest.mark.bigquery
def test_live_decimal_and_timestamp_types(live):
    """NUMERIC(12,2) from Parquet decimal128 and TIMESTAMP from UTC timestamps load exactly."""
    cfg, bq = live
    r = Runner(cfg, None, bq)
    r.init()
    d = payments_live_date()                                          # inside the Sandbox 60-day retention
    t = cfg.table("payments")
    ts = payment_ts(cfg, d)
    _land(cfg, r, "payments", d, payment_rows(ts), "ext-live-2", "run")
    r.load(d, [t])
    got = bq.query(f"SELECT amount, updated_at, _loaded_at IS NOT NULL AS has_loaded_at "
                   f"FROM `{bq.project}.{cfg.bq_raw_dataset}.payments` WHERE _ingestion_date = '{d.isoformat()}'")
    assert got[0]["amount"] == Decimal("9999999999.99")
    assert got[0]["updated_at"] == ts and got[0]["has_loaded_at"]


# ---------------------------------------------------------------------------------------------------------------
# Offline check (default suite): the fixtures above produce manifests whose timestamp fields BigQuery can parse.
# ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("table, d, rows, expected", [
    ("regions", date(2026, 7, 2), REGION_ROWS,
     {"window_start": "2026-07-01T16:00:00+00:00", "window_end": "2026-07-02T16:00:00+00:00", "extract_lower": None}),
    ("payments", date(2026, 7, 3), payment_rows(datetime(2026, 7, 3, 15, 59, 59, 123456, tzinfo=UTC)),
     {"window_start": "2026-07-02T16:00:00+00:00", "window_end": "2026-07-03T16:00:00+00:00",
      "extract_lower": "2026-07-02T15:00:00+00:00"}),
])
def test_live_fixture_manifests_have_valid_timestamps(cfg, table, d, rows, expected):
    m = _land(cfg, Runner(cfg), table, d, rows, "ext-check", "run")
    for field, value in expected.items():
        assert getattr(m, field) == value
    for field in ("window_start", "window_end", "extract_lower", "extracted_at", "started_at", "finished_at"):
        value = getattr(m, field)
        if value is not None:
            parsed = datetime.fromisoformat(value)
            assert parsed.utcoffset() == timedelta(0), f"{field} must be UTC: {value}"
    # every TIMESTAMP column of dq_audit.ingestion_log that a load event copies from this manifest parses
    event = Runner._event(m, "load", "load-check", len(rows), "job-check", "loaded", None,
                          datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 1, 0, 0, 1, tzinfo=UTC), 0.0).row()
    for f in audit_bq_schema():
        if f.field_type == "TIMESTAMP" and event[f.name] is not None:
            datetime.fromisoformat(event[f.name])


def test_live_dates_are_inside_sandbox_retention(cfg):
    """The live tests' dynamic dates stay well inside the Sandbox 60-day partition retention and still go
    through the production Asia/Manila -> UTC windows."""
    for table, d in (("regions", regions_live_date()), ("payments", payments_live_date())):
        assert 0 < (date.today() - d).days < SANDBOX_RETENTION_DAYS
        w = _window(cfg, table, d)
        assert w.end - w.start == timedelta(days=1) and w.start.utcoffset() == timedelta(0)
        assert w.start == datetime(d.year, d.month, d.day, tzinfo=cfg.tz).astimezone(UTC)
    w = _window(cfg, "payments", payments_live_date())
    assert w.lower == w.start - timedelta(minutes=60)                  # incremental lookback
    assert w.start <= payment_ts(cfg, payments_live_date()) < w.end    # payment row inside its business day
    assert _window(cfg, "regions", regions_live_date()).lower is None  # static table: full window
