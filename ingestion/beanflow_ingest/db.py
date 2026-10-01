"""PostgreSQL access for extraction: one read-only REPEATABLE READ snapshot per batch.

Every table in a batch is read from the same snapshot, so orders, items and
payments are mutually consistent, and the count query sees exactly the rows the
data query returns.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import psycopg
from psycopg import IsolationLevel, sql

from .config import PgSettings


def connect(settings: PgSettings, dbname: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(**settings.connect_kwargs(dbname))
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()
    return conn


@contextmanager
def snapshot(conn: psycopg.Connection) -> Iterator["Snapshot"]:
    """Read-only REPEATABLE READ transaction; rolled back at the end (nothing is ever written)."""
    conn.rollback()
    conn.isolation_level = IsolationLevel.REPEATABLE_READ
    conn.read_only = True
    try:
        with conn.transaction():
            yield Snapshot(conn)
            raise psycopg.Rollback()          # read-only: always end with ROLLBACK
    finally:
        conn.isolation_level = None
        conn.read_only = None


class Snapshot:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        # First statement fixes the snapshot; now() is the transaction start time.
        self.extracted_at: datetime = conn.execute("SELECT now()").fetchone()[0]

    def columns(self, schema: str, table: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT column_name, data_type, numeric_precision, numeric_scale
                 FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position""", (schema, table)).fetchall()
        return [dict(zip(("column_name", "data_type", "numeric_precision", "numeric_scale"), r)) for r in rows]

    def scalar(self, query: sql.Composable, params: dict) -> object:
        return self.conn.execute(query, params).fetchone()[0]

    def stream(self, query: sql.Composable, params: dict, chunk_rows: int) -> Iterator[list[tuple]]:
        with self.conn.cursor(name="beanflow_extract") as cur:
            cur.itersize = chunk_rows
            cur.execute(query, params)
            while rows := cur.fetchmany(chunk_rows):
                yield rows
