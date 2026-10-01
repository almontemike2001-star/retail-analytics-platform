"""BigQuery access: datasets/tables (init), Parquet load jobs, audit appends, small queries.

* Data reaches BigQuery only through LOAD JOBS (free). No streaming inserts anywhere.
* Per-date loads target `table$YYYYMMDD` with WRITE_TRUNCATE -> one partition = one load of one file.
* Authentication: Application Default Credentials (gcloud auth application-default login). No key files.

`BigQueryBackend` is the interface the runner depends on; tests use an in-memory fake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

LABELS = {"pipeline": "beanflow", "layer": "bronze"}


@dataclass
class LoadResult:
    job_id: str
    output_rows: int


class BigQueryBackend(Protocol):
    project: str
    location: str

    def ensure_dataset(self, dataset: str) -> None: ...
    def ensure_table(self, table_id: str, schema: list, partition_field: str | None,
                     cluster_by: tuple[str, ...], description: str) -> None: ...
    def table_exists(self, table_id: str) -> bool: ...
    def delete_table(self, table_id: str) -> None: ...
    def load_parquet(self, path: Path, destination: str, *, write_disposition: str, job_id_prefix: str,
                     labels: dict) -> LoadResult: ...
    def append_json(self, table_id: str, rows: list[dict], schema: list) -> str: ...
    def query(self, sql: str) -> list[dict]: ...


_LEGACY_TYPES = {"INT64": "INTEGER", "FLOAT64": "FLOAT", "BOOL": "BOOLEAN", "STRUCT": "RECORD"}


def schema_signature(schema: list) -> list[tuple]:
    """Comparable schema form; BigQuery reports legacy type names (INTEGER, FLOAT, BOOLEAN) on read."""
    return [(f.name, _LEGACY_TYPES.get(f.field_type, f.field_type), f.mode or "NULLABLE",
             getattr(f, "precision", None), getattr(f, "scale", None)) for f in schema]


def partition_target(table_id: str, business_date: date) -> str:
    return f"{table_id}${business_date.strftime('%Y%m%d')}"


def job_id_prefix(table: str, business_date: date | None) -> str:
    return f"beanflow_{table}_{business_date.strftime('%Y%m%d') if business_date else 'all'}_"


def build_load_job_config(write_disposition: str, labels: dict):
    from google.cloud import bigquery
    if write_disposition not in ("WRITE_TRUNCATE", "WRITE_APPEND"):
        raise ValueError(write_disposition)
    return bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=write_disposition,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,     # tables come from `ingest init`
        autodetect=False,
        decimal_target_types=[bigquery.DecimalTargetType.NUMERIC, bigquery.DecimalTargetType.BIGNUMERIC],
        labels={**LABELS, **labels},
    )


class BigQueryClient:
    """Real backend (google-cloud-bigquery)."""

    def __init__(self, project: str, location: str, max_query_bytes: int):
        from google.cloud import bigquery
        self._bq = bigquery
        self.client = bigquery.Client(project=project, location=location)
        self.project, self.location, self.max_query_bytes = project, location, max_query_bytes

    def fq(self, table_id: str) -> str:
        return table_id if table_id.count(".") == 2 else f"{self.project}.{table_id}"

    def ensure_dataset(self, dataset: str) -> None:
        ds = self._bq.Dataset(f"{self.project}.{dataset}")
        ds.location = self.location
        ds.labels = dict(LABELS)
        self.client.create_dataset(ds, exists_ok=True)
        actual = self.client.get_dataset(f"{self.project}.{dataset}").location
        if actual.lower() != self.location.lower():
            raise RuntimeError(f"Dataset {dataset} is in {actual}, expected {self.location} (location is immutable)")

    def ensure_table(self, table_id, schema, partition_field, cluster_by, description) -> None:
        bq = self._bq
        t = bq.Table(self.fq(table_id), schema=schema)
        if partition_field:
            t.time_partitioning = bq.TimePartitioning(type_=bq.TimePartitioningType.DAY, field=partition_field)
        if cluster_by:
            t.clustering_fields = list(cluster_by)
        t.description = description
        t.labels = dict(LABELS)
        self.client.create_table(t, exists_ok=True)
        existing = self.client.get_table(self.fq(table_id))
        if schema_signature(schema) != schema_signature(existing.schema):
            raise RuntimeError(f"BigQuery table {table_id} schema differs from the explicit schema; "
                               f"run `ingest reset-dev --yes` (dev) or migrate it deliberately.")

    def table_exists(self, table_id: str) -> bool:
        from google.api_core.exceptions import NotFound
        try:
            self.client.get_table(self.fq(table_id))
            return True
        except NotFound:
            return False

    def delete_table(self, table_id: str) -> None:
        self.client.delete_table(self.fq(table_id), not_found_ok=True)

    def load_parquet(self, path, destination, *, write_disposition, job_id_prefix, labels) -> LoadResult:
        cfg = build_load_job_config(write_disposition, labels)
        with open(path, "rb") as f:
            job = self.client.load_table_from_file(f, self.fq(destination), job_config=cfg,
                                                   job_id_prefix=job_id_prefix, location=self.location)
        job.result()                                   # raises on failure with job.errors
        return LoadResult(job.job_id, int(job.output_rows or 0))

    def append_json(self, table_id, rows, schema) -> str:
        bq = self._bq
        cfg = bq.LoadJobConfig(schema=schema, source_format=bq.SourceFormat.NEWLINE_DELIMITED_JSON,
                               write_disposition=bq.WriteDisposition.WRITE_APPEND,
                               create_disposition=bq.CreateDisposition.CREATE_NEVER,
                               labels={**LABELS, "layer": "audit"})
        rows = [json.loads(json.dumps(r, default=str)) for r in rows]
        job = self.client.load_table_from_json(rows, self.fq(table_id), job_config=cfg,
                                               job_id_prefix="beanflow_audit_", location=self.location)
        job.result()
        return job.job_id

    def query(self, sql: str) -> list[dict]:
        cfg = self._bq.QueryJobConfig(maximum_bytes_billed=self.max_query_bytes, labels={**LABELS, "layer": "check"})
        return [dict(r.items()) for r in self.client.query(sql, job_config=cfg, location=self.location).result()]
