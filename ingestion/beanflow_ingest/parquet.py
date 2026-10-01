"""Permanent landing artifacts (immutable Parquet + _manifest.json) and temporary load artifacts.

Permanent:  data/landing/<table>/dt=YYYY-MM-DD/part-000.parquet   (source columns + 5 extraction metadata
            columns), written atomically, then made read-only. Never rewritten except by an explicit,
            guarded --force-reextract.
Temporary:  data/.load_tmp/<load_batch_id>/<table>.parquet       (permanent columns + _loaded_at), created
            for one BigQuery load and always deleted afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from .schemas import LANDING_METADATA, TableSchema

MANIFEST_NAME = "_manifest.json"
MANIFEST_VERSION = 1
COMPRESSION = "zstd"
ROW_GROUP_ROWS = 128_000


class LandingError(RuntimeError):
    """A landing artifact is missing, incomplete, modified or inconsistent."""


@dataclass
class Manifest:
    manifest_version: int
    table: str
    extract_batch_id: str
    run_mode: str
    extract_mode: str
    business_date: str
    window_start: str
    window_end: str
    extract_lower: str | None
    lookback_minutes: int
    source_rows: int
    rows_in_window: int
    rows_in_lookback: int
    parquet_rows: int
    parquet_file: str           # repo-relative
    file_size_bytes: int
    sha256: str
    schema_hash: str
    extracted_at: str
    started_at: str
    finished_at: str
    duration_s: float
    status: str                 # "complete"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_path(cls, path: Path) -> "Manifest":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (OSError, ValueError, TypeError) as exc:
            raise LandingError(f"Unreadable manifest {path}: {exc}") from None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parquet_row_count(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        write(tmp)
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        os.replace(tmp, path)            # atomic on POSIX, also over a read-only target
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def _make_read_only(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


# ---------------------------------------------------------------------------
# permanent landing artifact
# ---------------------------------------------------------------------------
def add_extract_metadata(table: pa.Table, tschema: TableSchema, *, extract_batch_id: str, extract_mode: str,
                         extracted_at: datetime, source_file: str, ingestion_date: date) -> pa.Table:
    n = table.num_rows
    values = {"_extract_batch_id": extract_batch_id, "_extract_mode": extract_mode, "_extracted_at": extracted_at,
              "_source_file": source_file, "_ingestion_date": ingestion_date}
    for name, typ in LANDING_METADATA:
        table = table.append_column(pa.field(name, typ, nullable=False), pa.array([values[name]] * n, type=typ))
    return table.cast(tschema.landing_arrow_schema())


def write_landing(path: Path, table: pa.Table, tschema: TableSchema) -> None:
    if not table.schema.equals(tschema.landing_arrow_schema()):
        raise LandingError(f"Refusing to write {path.name}: schema differs from {tschema.table} landing schema")
    _atomic_write(path, lambda tmp: pq.write_table(table, tmp, compression=COMPRESSION,
                                                   row_group_size=ROW_GROUP_ROWS))
    _make_read_only(path)


def write_manifest(directory: Path, manifest: Manifest) -> Path:
    path = directory / MANIFEST_NAME
    _atomic_write(path, lambda tmp: tmp.write_text(manifest.to_json(), encoding="utf-8"))
    _make_read_only(path)
    return path


def read_manifest(directory: Path) -> Manifest | None:
    path = directory / MANIFEST_NAME
    return Manifest.from_path(path) if path.is_file() else None


def is_complete(directory: Path, file_name: str) -> bool:
    m = read_manifest(directory)
    return bool(m and m.status == "complete" and (directory / file_name).is_file())


def verify_landing(path: Path, manifest: Manifest, tschema: TableSchema) -> None:
    """Prove the permanent file is exactly what its manifest describes."""
    if not path.is_file():
        raise LandingError(f"Landing file missing: {path}")
    if manifest.status != "complete":
        raise LandingError(f"{path}: manifest status is {manifest.status!r}, not complete")
    actual = sha256_file(path)
    if actual != manifest.sha256:
        raise LandingError(f"{path}: sha256 {actual} does not match manifest {manifest.sha256} (file was modified)")
    if manifest.schema_hash != tschema.hash:
        raise LandingError(f"{path}: written with schema {manifest.schema_hash[:12]}, current schema is "
                           f"{tschema.hash[:12]}; schema changed since extraction")
    if parquet_row_count(path) != manifest.parquet_rows:
        raise LandingError(f"{path}: row count differs from manifest")
    if not pq.read_schema(path).equals(tschema.landing_arrow_schema()):
        raise LandingError(f"{path}: Parquet schema differs from the explicit landing schema")


def list_landing_dates(landing_root: Path, table: str) -> list[date]:
    base = landing_root / table
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        if d.is_dir() and d.name.startswith("dt="):
            try:
                out.append(date.fromisoformat(d.name[3:]))
            except ValueError:
                continue
    return sorted(out)


# ---------------------------------------------------------------------------
# temporary load artifact
# ---------------------------------------------------------------------------
@contextmanager
def load_artifact(sources: list[Path], dest: Path, loaded_at: datetime, tschema: TableSchema) -> Iterator[Path]:
    """Create `dest` = concatenation of permanent landing files + constant _loaded_at; always delete it."""
    try:
        tables = [pq.read_table(p, schema=tschema.landing_arrow_schema()) for p in sources]
        table = pa.concat_tables(tables) if tables else tschema.landing_arrow_schema().empty_table()
        name, typ = "_loaded_at", pa.timestamp("us", tz="UTC")
        table = table.append_column(pa.field(name, typ, nullable=False), pa.array([loaded_at] * table.num_rows, type=typ))
        table = table.cast(tschema.load_arrow_schema())
        dest.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, dest, compression=COMPRESSION, row_group_size=ROW_GROUP_ROWS)
        yield dest
    finally:
        # Only this artifact's own file: tables load in parallel into the same <load_batch_id>/ directory,
        # which the caller removes once every table has finished (see Runner.load / replay_all).
        if dest.exists():
            dest.unlink()


def remove_tree(path: Path) -> None:
    """Delete a directory tree, including read-only landing files (used by reset-dev only)."""
    def _onerror(func, p, _exc):
        os.chmod(p, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        func(p)
    if path.exists():
        for root, dirs, files in os.walk(path):
            for n in files:
                os.chmod(os.path.join(root, n), stat.S_IWUSR | stat.S_IRUSR)
        shutil.rmtree(path, onexc=_onerror)
