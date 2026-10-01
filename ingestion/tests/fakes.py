"""In-memory BigQuery stand-in that enforces the semantics the pipeline relies on.

* tables must exist before a load (CREATE_NEVER)
* `table$YYYYMMDD` + WRITE_TRUNCATE replaces exactly that partition, and every row must belong to it
* whole-table WRITE_TRUNCATE replaces all partitions
* audit rows arrive through `append_json` (a load job in the real client)
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from beanflow_ingest.bigquery import LoadResult, build_load_job_config


@dataclass
class FakeTable:
    schema: list
    partition_field: str | None
    cluster_by: tuple
    partitions: dict = field(default_factory=dict)        # date -> pa.Table

    def all_rows(self) -> pa.Table | None:
        parts = [t for t in self.partitions.values() if t.num_rows]
        return pa.concat_tables(parts) if parts else None


class FakeBigQuery:
    def __init__(self, project: str = "fake-project", location: str = "asia-southeast1"):
        self.project, self.location = project, location
        self.datasets: set[str] = set()
        self.tables: dict[str, FakeTable] = {}
        self.load_calls: list[dict] = []
        self.audit_rows: list[dict] = []
        self.fail_loads: int = 0                 # make the next N loads raise
        self.row_skew: int = 0                   # add to reported output_rows (simulate a mismatch)
        self._job = 0

    def ensure_dataset(self, dataset):
        self.datasets.add(dataset)

    def ensure_table(self, table_id, schema, partition_field, cluster_by, description):
        self.tables.setdefault(table_id, FakeTable(schema, partition_field, tuple(cluster_by)))

    def table_exists(self, table_id):
        return table_id in self.tables

    def delete_table(self, table_id):
        self.tables.pop(table_id, None)

    def load_parquet(self, path: Path, destination: str, *, write_disposition, job_id_prefix, labels):
        cfg = build_load_job_config(write_disposition, labels)                # same config as the real client
        table_id, _, part = destination.partition("$")
        if table_id not in self.tables:
            raise RuntimeError(f"Not found: {table_id} (CREATE_NEVER)")
        data = pq.read_table(path)                                            # file must exist during the load
        self.load_calls.append({"path": str(path), "destination": destination, "config": cfg,
                                "rows": data.num_rows, "columns": data.column_names, "prefix": job_id_prefix})
        if self.fail_loads:
            self.fail_loads -= 1
            raise RuntimeError("simulated BigQuery load failure")
        t = self.tables[table_id]
        expected = [f.name for f in t.schema]
        if data.column_names != expected:
            raise RuntimeError(f"schema mismatch: {data.column_names} vs {expected}")
        if write_disposition != "WRITE_TRUNCATE":
            raise RuntimeError("pipeline must use WRITE_TRUNCATE for data tables")
        if part:
            d = date(int(part[:4]), int(part[4:6]), int(part[6:]))
            dates = set(data.column(t.partition_field).to_pylist())
            if dates - {d}:
                raise RuntimeError(f"rows outside partition {part}: {dates}")
            t.partitions[d] = data
        else:
            t.partitions = {}
            for d in set(data.column(t.partition_field).to_pylist()):
                t.partitions[d] = data.filter(pc.equal(data.column(t.partition_field), pa.scalar(d)))
        self._job += 1
        return LoadResult(f"{job_id_prefix}{self._job:04d}", data.num_rows + self.row_skew)

    def append_json(self, table_id, rows, schema):
        if table_id not in self.tables:
            raise RuntimeError(f"Not found: {table_id}")
        names = {f.name for f in schema}
        for r in rows:
            assert set(r) == names, set(r) ^ names
        self.audit_rows.extend(rows)
        return f"beanflow_audit_{len(self.audit_rows)}"

    # minimal SQL for check / reconcile --full
    def _rows(self, fq: str) -> pa.Table | None:
        table_id = ".".join(fq.strip("`").split(".")[-2:])
        return self.tables[table_id].all_rows()

    def query(self, sql: str):
        if m := re.fullmatch(r"SELECT MAX\((\w+)\) AS m FROM (`[^`]+`)", sql):
            t = self._rows(m.group(2))
            return [{"m": pc.max(t.column(m.group(1))).as_py() if t is not None else None}]
        if m := re.fullmatch(r"SELECT COUNT\(DISTINCT (\w+)\) AS n(?:, MAX\((\w+)\) AS m)? FROM (`[^`]+`)", sql):
            t = self._rows(m.group(3))
            n = len(set(t.column(m.group(1)).to_pylist())) if t is not None else 0
            out = {"n": n}
            if m.group(2):
                out["m"] = pc.max(t.column(m.group(2))).as_py() if t is not None else None
            return [out]
        if m := re.fullmatch(r"SELECT DISTINCT (\w+) AS k FROM (`[^`]+`)", sql):
            t = self._rows(m.group(2))
            return [{"k": k} for k in set(t.column(m.group(1)).to_pylist())] if t is not None else []
        raise NotImplementedError(sql)

    def partition_rows(self, table_id: str) -> dict:
        return {d: t.num_rows for d, t in self.tables[table_id].partitions.items()}


def versions(table: pa.Table, pk: str, cursor: str = "updated_at") -> dict:
    out = defaultdict(list)
    for k, u in zip(table.column(pk).to_pylist(), table.column(cursor).to_pylist()):
        out[k].append(u)
    return out
