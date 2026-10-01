"""Explicit table schemas: one definition -> PostgreSQL expectations, PyArrow schema, BigQuery schema.

Logical types (ingestion/schemas/<table>.yml):

    logical        PostgreSQL (information_schema.data_type)       PyArrow                  BigQuery
    int64          smallint | integer | bigint                     int64                    INT64
    string         character varying | text | character            string                   STRING
    bool           boolean                                         bool                     BOOL
    date           date                                            date32                   DATE
    timestamp      timestamp with time zone                        timestamp[us, UTC]       TIMESTAMP
    decimal(P,S)   numeric with precision P and scale S            decimal128(P, S)         NUMERIC(P, S)

Schema drift (missing column, unexpected column, incompatible type) fails BEFORE extraction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import yaml

# Metadata columns in the permanent landing Parquet (in this order).
LANDING_METADATA: tuple[tuple[str, pa.DataType], ...] = (
    ("_extract_batch_id", pa.string()),
    ("_extract_mode", pa.string()),
    ("_extracted_at", pa.timestamp("us", tz="UTC")),
    ("_source_file", pa.string()),
    ("_ingestion_date", pa.date32()),
)
# Added only to the temporary load artifact.
LOAD_METADATA: tuple[tuple[str, pa.DataType], ...] = (("_loaded_at", pa.timestamp("us", tz="UTC")),)

_DECIMAL = re.compile(r"^decimal\((\d+),\s*(\d+)\)$")
_SIMPLE = {"int64", "string", "bool", "date", "timestamp"}
_PG_TYPES = {
    "int64": {"smallint", "integer", "bigint"},
    "string": {"character varying", "text", "character"},
    "bool": {"boolean"},
    "date": {"date"},
    "timestamp": {"timestamp with time zone"},
}
_BQ_TYPES = {"int64": "INT64", "string": "STRING", "bool": "BOOL", "date": "DATE", "timestamp": "TIMESTAMP"}


class SchemaError(ValueError):
    """Malformed schema definition."""


class SchemaDriftError(RuntimeError):
    """The live source table does not match its explicit schema."""


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool

    @property
    def decimal(self) -> tuple[int, int] | None:
        m = _DECIMAL.match(self.type)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def arrow_type(self) -> pa.DataType:
        if dec := self.decimal:
            return pa.decimal128(*dec)
        return {"int64": pa.int64(), "string": pa.string(), "bool": pa.bool_(), "date": pa.date32(),
                "timestamp": pa.timestamp("us", tz="UTC")}[self.type]


@dataclass(frozen=True)
class TableSchema:
    table: str
    columns: tuple[Column, ...]
    source_path: Path

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(name)

    @property
    def hash(self) -> str:
        canon = json.dumps({"table": self.table, "columns": [[c.name, c.type, c.nullable] for c in self.columns]},
                           sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode()).hexdigest()

    # -- PyArrow ---------------------------------------------------------------------
    def source_arrow_fields(self) -> list[pa.Field]:
        # Bronze accepts whatever the source sends: source columns are nullable in Arrow/BigQuery.
        return [pa.field(c.name, c.arrow_type(), nullable=True) for c in self.columns]

    def landing_arrow_schema(self) -> pa.Schema:
        meta = [pa.field(n, t, nullable=False) for n, t in LANDING_METADATA]
        return pa.schema(self.source_arrow_fields() + meta)

    def load_arrow_schema(self) -> pa.Schema:
        meta = [pa.field(n, t, nullable=False) for n, t in LANDING_METADATA + LOAD_METADATA]
        return pa.schema(self.source_arrow_fields() + meta)

    # -- BigQuery --------------------------------------------------------------------
    def bq_schema(self) -> list:
        from google.cloud import bigquery
        fields = []
        for c in self.columns:
            if dec := c.decimal:
                fields.append(bigquery.SchemaField(c.name, "NUMERIC", mode="NULLABLE", precision=dec[0], scale=dec[1]))
            else:
                fields.append(bigquery.SchemaField(c.name, _BQ_TYPES[c.type], mode="NULLABLE"))
        for name, t in LANDING_METADATA + LOAD_METADATA:
            bq_type = "STRING" if pa.types.is_string(t) else "DATE" if pa.types.is_date32(t) else "TIMESTAMP"
            fields.append(bigquery.SchemaField(name, bq_type, mode="REQUIRED"))
        return fields

    # -- PostgreSQL ------------------------------------------------------------------
    def check_source(self, pg_columns: list[dict]) -> None:
        """pg_columns: dicts with column_name, data_type, numeric_precision, numeric_scale."""
        live = {c["column_name"]: c for c in pg_columns}
        problems = []
        for col in self.columns:
            pc = live.get(col.name)
            if pc is None:
                problems.append(f"missing column {col.name!r}")
                continue
            if dec := col.decimal:
                ok = pc["data_type"] == "numeric" and (pc["numeric_precision"], pc["numeric_scale"]) == dec
                expected = f"numeric({dec[0]},{dec[1]})"
            else:
                ok = pc["data_type"] in _PG_TYPES[col.type]
                expected = " | ".join(sorted(_PG_TYPES[col.type]))
            if not ok:
                got = pc["data_type"] + (f"({pc['numeric_precision']},{pc['numeric_scale']})"
                                         if pc["data_type"] == "numeric" else "")
                problems.append(f"incompatible type for {col.name!r}: source {got}, schema expects {expected}")
        for name in live:
            if name not in self.names:
                problems.append(f"unexpected column {name!r} (add it to {self.source_path.name} first)")
        if problems:
            raise SchemaDriftError(f"Schema drift in {self.table}: " + "; ".join(problems))


def load_schema(path: Path, expected_table: str | None = None) -> TableSchema:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SchemaError(f"Cannot read schema {path}: {exc}") from None
    if not isinstance(doc, dict) or set(doc) - {"table", "columns"} or "table" not in doc or "columns" not in doc:
        raise SchemaError(f"{path}: expected keys 'table' and 'columns' only")
    if expected_table and doc["table"] != expected_table:
        raise SchemaError(f"{path}: declares table {doc['table']!r}, config expects {expected_table!r}")
    cols_raw = doc["columns"]
    if not isinstance(cols_raw, list) or not cols_raw:
        raise SchemaError(f"{path}: columns must be a non-empty list")
    cols, seen = [], set()
    for c in cols_raw:
        if not isinstance(c, dict) or set(c) != {"name", "type", "nullable"}:
            raise SchemaError(f"{path}: each column needs exactly name, type, nullable (got {c!r})")
        name, typ, nullable = c["name"], str(c["type"]).strip(), c["nullable"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name.startswith("_"):
            raise SchemaError(f"{path}: invalid column name {name!r}")
        if name in seen:
            raise SchemaError(f"{path}: duplicate column {name!r}")
        if typ not in _SIMPLE and not _DECIMAL.match(typ):
            raise SchemaError(f"{path}: unsupported type {typ!r} for {name!r}")
        if (m := _DECIMAL.match(typ)) and not (1 <= int(m.group(2)) <= int(m.group(1)) <= 38):
            raise SchemaError(f"{path}: invalid decimal {typ!r} for {name!r}")
        if not isinstance(nullable, bool):
            raise SchemaError(f"{path}: nullable must be true/false for {name!r}")
        seen.add(name)
        cols.append(Column(name, typ, nullable))
    return TableSchema(doc["table"], tuple(cols), Path(path))
