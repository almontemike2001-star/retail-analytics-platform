"""OPTIONAL live BigQuery smoke test - excluded by default.

Run explicitly with your own ADC credentials:
    GCP_PROJECT_ID=<project> pytest -m bigquery
It creates throw-away datasets (raw_pos_test_<random>, dq_audit_test_<random>) and deletes them afterwards.
"""

import os
import uuid
from datetime import date, datetime, timezone

import pyarrow as pa
import pytest

from beanflow_ingest import parquet as pqm
from beanflow_ingest.config import load_config
from beanflow_ingest.reconcile import read_local
from beanflow_ingest.runner import Runner

pytestmark = pytest.mark.bigquery


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


def test_live_init_load_replay(live):
    cfg, bq = live
    r = Runner(cfg, None, bq)
    r.init()
    d = date(2026, 7, 2)
    t = cfg.table("regions")
    s = r.schema(t)
    path = cfg.landing_file("regions", d)
    rows = [{"region_id": i, "region_name": f"Region {i}"} for i in range(1, 5)]
    tbl = pqm.add_extract_metadata(pa.Table.from_pylist(rows, schema=pa.schema(s.source_arrow_fields())), s,
                                   extract_batch_id="ext-live", extract_mode="full",
                                   extracted_at=datetime.now(timezone.utc),
                                   source_file=path.relative_to(cfg.repo_root).as_posix(), ingestion_date=d)
    pqm.write_landing(path, tbl, s)
    pqm.write_manifest(path.parent, pqm.Manifest(1, "regions", "ext-live", "bootstrap", "full", d.isoformat(), "s", "e",
                                                 None, 0, 4, 4, 0, 4, path.relative_to(cfg.repo_root).as_posix(),
                                                 path.stat().st_size, pqm.sha256_file(path), s.hash, "x", "x", "x",
                                                 0.0, "complete"))
    r.load(d, [t])
    r.load(d, [t])                                                    # replay: still 4 rows
    n = bq.query(f"SELECT COUNT(*) AS n FROM `{bq.project}.{cfg.bq_raw_dataset}.regions` "
                 f"WHERE _ingestion_date = '{d.isoformat()}'")[0]["n"]
    assert n == 4
    assert [e["status"] for e in read_local(cfg.abs(cfg.audit_local_path))] == ["loaded", "replayed"]


def test_live_decimal_and_timestamp_types(live):
    """NUMERIC(12,2) from Parquet decimal128 and TIMESTAMP from UTC timestamps load exactly."""
    from decimal import Decimal
    cfg, bq = live
    r = Runner(cfg, None, bq)
    r.init()
    d = date(2026, 7, 3)
    t = cfg.table("payments")
    s = r.schema(t)
    ts = datetime(2026, 7, 2, 23, 59, 59, 123456, tzinfo=timezone.utc)
    rows = [{"payment_id": 1, "order_id": 10, "payment_method": "card", "amount": Decimal("9999999999.99"),
             "payment_status": "paid", "paid_at": ts, "updated_at": ts}]
    path = cfg.landing_file("payments", d)
    tbl = pqm.add_extract_metadata(pa.Table.from_pylist(rows, schema=pa.schema(s.source_arrow_fields())), s,
                                   extract_batch_id="ext-live-2", extract_mode="incremental",
                                   extracted_at=datetime.now(timezone.utc),
                                   source_file=path.relative_to(cfg.repo_root).as_posix(), ingestion_date=d)
    pqm.write_landing(path, tbl, s)
    pqm.write_manifest(path.parent, pqm.Manifest(1, "payments", "ext-live-2", "run", "incremental", d.isoformat(),
                                                 "s", "e", None, 60, 1, 1, 0, 1,
                                                 path.relative_to(cfg.repo_root).as_posix(), path.stat().st_size,
                                                 pqm.sha256_file(path), s.hash, "x", "x", "x", 0.0, "complete"))
    r.load(d, [t])
    got = bq.query(f"SELECT amount, updated_at, _loaded_at IS NOT NULL AS has_loaded_at "
                   f"FROM `{bq.project}.{cfg.bq_raw_dataset}.payments` WHERE _ingestion_date = '{d.isoformat()}'")
    assert got[0]["amount"] == Decimal("9999999999.99")
    assert got[0]["updated_at"] == ts and got[0]["has_loaded_at"]
