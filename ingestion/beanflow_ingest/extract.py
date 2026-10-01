"""Column-explicit extraction queries and streaming into Arrow.

Predicates (cursor = the table's cursor_column, normally updated_at):

    full         (static tables)    no WHERE clause
    bootstrap    (mutable tables)   cursor < :window_end
    incremental  (mutable tables)   cursor >= :extract_lower AND cursor < :window_end

Rows are always ordered by primary key so identical source states produce
identical files. Counts use the same predicate inside the same snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa
from psycopg import sql

from .config import TableConfig
from .db import Snapshot
from .schemas import TableSchema
from .windows import Window

EXTRACT_MODES = ("bootstrap", "full", "incremental")


@dataclass
class ExtractResult:
    table: pa.Table               # source columns only (metadata is added by parquet.py)
    extract_mode: str
    source_rows: int
    rows_in_window: int
    rows_in_lookback: int


def effective_mode(tcfg: TableConfig, requested: str) -> str:
    """Static tables are always extracted in full; mutable tables use the requested mode."""
    if requested not in ("bootstrap", "incremental"):
        raise ValueError(f"requested mode must be bootstrap or incremental, got {requested!r}")
    return "full" if not tcfg.incremental else requested


def predicate(tcfg: TableConfig, mode: str, window: Window) -> tuple[sql.Composable, dict]:
    if mode == "full":
        return sql.SQL(""), {}
    cur = sql.Identifier(tcfg.cursor_column)
    if mode == "bootstrap":
        return sql.SQL(" WHERE {c} < %(window_end)s").format(c=cur), {"window_end": window.end}
    if mode == "incremental":
        return (sql.SQL(" WHERE {c} >= %(extract_lower)s AND {c} < %(window_end)s").format(c=cur),
                {"extract_lower": window.lower, "window_end": window.end})
    raise ValueError(f"unknown extract mode {mode!r}")


def build_select(schema_name: str, tcfg: TableConfig, tschema: TableSchema, mode: str,
                 window: Window) -> tuple[sql.Composable, dict]:
    where, params = predicate(tcfg, mode, window)
    q = sql.SQL("SELECT {cols} FROM {tbl}{where} ORDER BY {pk}").format(
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in tschema.names),
        tbl=sql.Identifier(schema_name, tcfg.name), where=where,
        pk=sql.SQL(", ").join(sql.Identifier(c) for c in tcfg.primary_key))
    return q, params


def build_count(schema_name: str, tcfg: TableConfig, mode: str, window: Window) -> tuple[sql.Composable, dict]:
    where, params = predicate(tcfg, mode, window)
    return sql.SQL("SELECT count(*) FROM {tbl}{where}").format(tbl=sql.Identifier(schema_name, tcfg.name),
                                                                where=where), params


def rows_to_arrow(rows: list[tuple], tschema: TableSchema) -> pa.RecordBatch:
    fields = tschema.source_arrow_fields()
    cols = list(zip(*rows)) if rows else [[] for _ in fields]
    return pa.RecordBatch.from_arrays([pa.array(list(v), type=f.type) for v, f in zip(cols, fields)],
                                      schema=pa.schema(fields))


def extract_table(snap: Snapshot, schema_name: str, tcfg: TableConfig, tschema: TableSchema, mode: str,
                  window: Window, chunk_rows: int) -> ExtractResult:
    tschema.check_source(snap.columns(schema_name, tcfg.name))       # fail before reading any rows
    count_q, count_p = build_count(schema_name, tcfg, mode, window)
    source_rows = int(snap.scalar(count_q, count_p))
    if mode == "incremental":
        in_window_q = sql.SQL("SELECT count(*) FROM {tbl} WHERE {c} >= %(window_start)s AND {c} < %(window_end)s"
                              ).format(tbl=sql.Identifier(schema_name, tcfg.name), c=sql.Identifier(tcfg.cursor_column))
        rows_in_window = int(snap.scalar(in_window_q, {"window_start": window.start, "window_end": window.end}))
    else:
        rows_in_window = source_rows
    select_q, select_p = build_select(schema_name, tcfg, tschema, mode, window)
    batches = [rows_to_arrow(chunk, tschema) for chunk in snap.stream(select_q, select_p, chunk_rows)]
    table = pa.Table.from_batches(batches, schema=pa.schema(tschema.source_arrow_fields())) if batches \
        else pa.Table.from_batches([], schema=pa.schema(tschema.source_arrow_fields()))
    return ExtractResult(table, mode, source_rows, rows_in_window, source_rows - rows_in_window)
