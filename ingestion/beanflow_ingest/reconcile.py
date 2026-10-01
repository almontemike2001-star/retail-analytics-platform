"""Audit events (dq_audit.ingestion_log), pass/fail rules, local and full reconciliation.

Grain: one row per extraction/load/table event.
  * extraction event  -> load_batch_id NULL, bq_loaded_rows NULL; passes when source_rows = parquet_rows
  * load/replay event -> same extract_batch_id as the landing file, new load_batch_id;
                         passes when parquet_rows = bq_loaded_rows

For incremental tables the counts are row VERSIONS changed in the window (incl. the lookback), not
table sizes. Table-size consistency is checked separately by `reconcile --full`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path

STATUSES = ("extracted", "loaded", "replayed", "skipped", "mismatch", "failed")


@dataclass
class AuditEvent:
    extract_batch_id: str | None
    load_batch_id: str | None
    business_date: str
    table_name: str
    run_mode: str
    extract_mode: str | None
    window_start: str | None
    window_end: str | None
    extract_lower: str | None
    lookback_minutes: int | None
    source_rows: int | None
    rows_in_window: int | None
    rows_in_lookback: int | None
    parquet_rows: int | None
    bq_loaded_rows: int | None
    parquet_file: str | None
    file_sha256: str | None
    schema_hash: str | None
    bq_job_id: str | None
    status: str
    error_message: str | None
    started_at: str
    finished_at: str
    duration_s: float

    def row(self) -> dict:
        return asdict(self)


def audit_bq_schema() -> list:
    from google.cloud import bigquery as bq
    types = {"lookback_minutes": "INT64", "source_rows": "INT64", "rows_in_window": "INT64",
             "rows_in_lookback": "INT64", "parquet_rows": "INT64", "bq_loaded_rows": "INT64",
             "business_date": "DATE", "window_start": "TIMESTAMP", "window_end": "TIMESTAMP",
             "extract_lower": "TIMESTAMP", "started_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
             "duration_s": "FLOAT64"}
    required = {"business_date", "table_name", "run_mode", "status", "started_at", "finished_at", "duration_s"}
    return [bq.SchemaField(f.name, types.get(f.name, "STRING"), mode="REQUIRED" if f.name in required else "NULLABLE")
            for f in fields(AuditEvent)]


def extract_status(source_rows: int, parquet_rows: int) -> str:
    return "extracted" if source_rows == parquet_rows else "mismatch"


def load_status(parquet_rows: int, bq_loaded_rows: int, replay: bool) -> str:
    if parquet_rows != bq_loaded_rows:
        return "mismatch"
    return "replayed" if replay else "loaded"


def passed(status: str) -> bool:
    return status in ("extracted", "loaded", "replayed", "skipped")


def append_local(path: Path, events: list[AuditEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e.row(), sort_keys=True, default=str) + "\n")


def read_local(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# reconcile --full : source table vs. all Bronze versions
# ---------------------------------------------------------------------------
@dataclass
class FullCheck:
    table: str
    source_rows: int
    bronze_distinct_pk: int
    source_max_updated_at: str | None
    bronze_max_updated_at: str | None
    missing_in_bronze: int | None
    extra_in_bronze: int | None
    ok: bool
    note: str = ""


def compare_full(table: str, source_rows: int, bronze_pk: int, src_max, bronze_max,
                 missing: int | None, extra: int | None) -> FullCheck:
    def norm(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    ok = source_rows == bronze_pk and norm(src_max) == norm(bronze_max) and not missing and not extra
    note = "" if ok else ("counts differ" if source_rows != bronze_pk else
                          "max(updated_at) differs" if norm(src_max) != norm(bronze_max) else "primary-key sets differ")
    return FullCheck(table, source_rows, bronze_pk, norm(src_max), norm(bronze_max), missing, extra, ok, note)
