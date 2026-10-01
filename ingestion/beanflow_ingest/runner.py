"""Orchestration: bootstrap / extract / load / run / replay-all / reconcile / reset-dev.

Rules (approved Phase 3 design)
* Extraction for business date D reads one REPEATABLE READ snapshot for all requested tables.
* A completed landing artifact is immutable: a normal rerun REPLAYS it (no re-extraction).
  `--force-reextract` is only allowed for the most recent extracted date of a table.
* Incremental extraction for D requires a complete landing artifact for D-1 (bootstrap or incremental)
  unless `--allow-gap` is given, so Bronze history can never silently skip a day.
* Every load builds a temporary artifact (+ _loaded_at), loads it with WRITE_TRUNCATE into
  `table$YYYYMMDD`, deletes it, and re-verifies the permanent file's sha256.
* _extract_batch_id is preserved forever; every load/replay gets a new load_batch_id and _loaded_at.
* Bronze is never deduplicated here (version identity = primary key + updated_at; Silver dedupes).
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import db
from .bigquery import BigQueryBackend, job_id_prefix, partition_target
from .config import IngestConfig, PgSettings, TableConfig
from .extract import effective_mode, extract_table
from .parquet import (LandingError, Manifest, add_extract_metadata, is_complete, list_landing_dates,
                      load_artifact, parquet_row_count, read_manifest, remove_tree, sha256_file,
                      verify_landing, write_landing, write_manifest)
from .reconcile import (AuditEvent, FullCheck, append_local, audit_bq_schema, compare_full, extract_status,
                        iso, load_status, passed, read_local)
from .schemas import TableSchema, load_schema
from .windows import Window, bootstrap_window, ensure_closed, full_window, incremental_window

log = logging.getLogger("beanflow_ingest")
UTC = timezone.utc


class IngestError(RuntimeError):
    """One or more tables failed; audit events were still written."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts_id(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


@dataclass
class Outcome:
    table: str
    status: str
    events: list[AuditEvent] = field(default_factory=list)
    message: str = ""


class Runner:
    def __init__(self, cfg: IngestConfig, pg: PgSettings | None = None, bq: BigQueryBackend | None = None,
                 now_fn: Callable[[], datetime] = utcnow, pg_dbname: str | None = None):
        self.cfg, self.pg, self.bq, self.now = cfg, pg, bq, now_fn
        self.pg_dbname = pg_dbname
        self._schemas: dict[str, TableSchema] = {}

    # ------------------------------------------------------------------ helpers
    def schema(self, t: TableConfig) -> TableSchema:
        if t.name not in self._schemas:
            s = load_schema(t.schema_file, expected_table=t.name)
            for col in (*t.primary_key, *t.cluster_by, *([t.cursor_column] if t.cursor_column else [])):
                if col not in s.names:
                    raise LandingError(f"{t.name}: config column {col!r} is not in {t.schema_file.name}")
            if t.cursor_column and s.column(t.cursor_column).type != "timestamp":
                raise LandingError(f"{t.name}: cursor_column {t.cursor_column!r} must be a timestamp")
            self._schemas[t.name] = s
        return self._schemas[t.name]

    def raw_table_id(self, t: TableConfig) -> str:
        return f"{self.cfg.bq_raw_dataset}.{t.bq_table}"

    @property
    def audit_table_id(self) -> str:
        return f"{self.cfg.bq_audit_dataset}.{self.cfg.bq_audit_table}"

    def _window(self, t: TableConfig, mode: str, d: date) -> Window:
        if mode == "incremental":
            return incremental_window(d, self.cfg.tz, t.lookback_minutes)
        if mode == "bootstrap":
            return bootstrap_window(d, self.cfg.tz)
        return full_window(d, self.cfg.tz)

    def _connect(self):
        if self.pg is None:
            raise IngestError("PostgreSQL settings are required for this command")
        return db.connect(self.pg, self.pg_dbname)

    def _require_bq(self) -> BigQueryBackend:
        if self.bq is None:
            raise IngestError("GCP is not configured (set GCP_PROJECT_ID and run `gcloud auth application-default "
                              "login`; see docs/setup_gcp.md)")
        return self.bq

    def write_audit(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        append_local(self.cfg.abs(self.cfg.audit_local_path), events)
        if self.bq is None:
            log.warning("GCP not configured: %d audit event(s) kept locally in %s only", len(events),
                        self.cfg.audit_local_path)
            return
        self.bq.append_json(self.audit_table_id, [e.row() for e in events], audit_bq_schema())

    @staticmethod
    def _load_events_for(audit: list[dict], m: Manifest) -> list[dict]:
        """Load events (oldest first) that loaded this landing artifact.

        * per-date load/replay: same table and extract_batch_id
        * replay-all: same table, coverage [window_start, window_end] contains the artifact's window,
          and the replay started after the artifact was extracted
        """
        out = []
        for r in audit:
            if r.get("table_name") != m.table or not r.get("load_batch_id"):
                continue
            if r.get("run_mode") == "replay_all":
                if (r.get("window_start") and r["window_start"] <= m.window_start and m.window_end <= r["window_end"]
                        and r["started_at"] >= m.finished_at):
                    out.append(r)
            elif r.get("extract_batch_id") == m.extract_batch_id:
                out.append(r)
        return out

    def _previously_loaded(self, m: Manifest) -> bool:
        return any(r.get("status") in ("loaded", "replayed")
                   for r in self._load_events_for(read_local(self.cfg.abs(self.cfg.audit_local_path)), m))

    # ------------------------------------------------------------------ init / check
    def init(self) -> list[str]:
        bq = self._require_bq()
        done = []
        for ds in (self.cfg.bq_raw_dataset, self.cfg.bq_audit_dataset):
            bq.ensure_dataset(ds)
            done.append(f"dataset {ds} ({self.cfg.bq_location})")
        for t in self.cfg.tables:
            s = self.schema(t)
            bq.ensure_table(self.raw_table_id(t), s.bq_schema(), self.cfg.partition_field, t.cluster_by,
                            f"Bronze copy of {self.cfg.source_schema}.{t.name} (append-only source versions)")
            done.append(f"table {self.raw_table_id(t)}")
        bq.ensure_table(self.audit_table_id, audit_bq_schema(), "business_date", ("table_name", "status"),
                        "BeanFlow ingestion audit: one row per extraction/load/table event")
        done.append(f"table {self.audit_table_id}")
        return done

    def check(self) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []
        for t in self.cfg.tables:
            try:
                self.schema(t)
                results.append((f"schema {t.name}", True, f"{len(self.schema(t).columns)} columns"))
            except Exception as exc:                                           # noqa: BLE001
                results.append((f"schema {t.name}", False, str(exc)))
        try:
            with self._connect() as conn, db.snapshot(conn) as snap:
                for t in self.cfg.tables:
                    try:
                        self.schema(t).check_source(snap.columns(self.cfg.source_schema, t.name))
                        results.append((f"source {self.cfg.source_schema}.{t.name}", True, "matches schema"))
                    except Exception as exc:                                   # noqa: BLE001
                        results.append((f"source {self.cfg.source_schema}.{t.name}", False, str(exc)))
                src_max = {t.name: snap.scalar(*_max_query(self.cfg, t)) for t in self.cfg.tables if t.incremental}
        except Exception as exc:                                               # noqa: BLE001
            results.append(("postgres", False, str(exc)))
            src_max = {}
        if self.bq is None:
            results.append(("bigquery", False, "GCP not configured (GCP_PROJECT_ID unset) - local-only mode"))
            return results
        for t in self.cfg.tables:
            exists = self.bq.table_exists(self.raw_table_id(t))
            results.append((f"bigquery {self.raw_table_id(t)}", exists, "exists" if exists else "missing: run init"))
            if exists and t.name in src_max:
                rows = self.bq.query(f"SELECT MAX({t.cursor_column}) AS m FROM `{self.bq.project}."
                                     f"{self.raw_table_id(t)}`")
                bronze_max = rows[0]["m"] if rows else None
                ahead = bronze_max is not None and src_max[t.name] is not None and bronze_max > src_max[t.name]
                results.append((f"freshness {t.name}", not ahead,
                                "Bronze holds data NEWER than the source - reset Postgres, landing and Bronze "
                                "together" if ahead else "Bronze not ahead of source"))
        return results

    # ------------------------------------------------------------------ extraction
    def extract(self, d: date, tables: list[TableConfig], requested_mode: str, run_mode: str,
                force: bool = False, allow_gap: bool = False) -> list[Outcome]:
        now = self.now()
        batch_id = f"ext-{'boot' if requested_mode == 'bootstrap' else 'inc'}-{d:%Y%m%d}-{_ts_id(now)}"
        outcomes, todo = [], []
        landing_root = self.cfg.abs(self.cfg.landing_root)
        for t in tables:
            mode = effective_mode(t, requested_mode)
            window = self._window(t, mode, d)
            ensure_closed(window, now, self.cfg.settle_minutes)
            directory = self.cfg.landing_dir(t.name, d)
            if is_complete(directory, self.cfg.file_name):
                if not force:
                    outcomes.append(Outcome(t.name, "skipped", message="landing artifact complete - will replay"))
                    continue
                latest = max(list_landing_dates(landing_root, t.name))
                if d != latest:
                    raise LandingError(f"{t.name}: --force-reextract only allowed for the most recent extracted date "
                                       f"({latest}); re-extracting {d} would lose intermediate source versions")
            if mode == "incremental" and not allow_gap and not is_complete(
                    self.cfg.landing_dir(t.name, d - timedelta(days=1)), self.cfg.file_name):
                raise LandingError(f"{t.name}: no complete landing artifact for {d - timedelta(days=1)}; extract the "
                                   f"previous day (or bootstrap) first, or pass --allow-gap")
            todo.append((t, mode, window))
        if not todo:
            return outcomes

        events: list[AuditEvent] = []
        failures = []
        with self._connect() as conn, db.snapshot(conn) as snap:
            for t, _, _ in todo:                       # preflight: fail on drift before writing anything
                self.schema(t).check_source(snap.columns(self.cfg.source_schema, t.name))
            for t, mode, window in todo:
                t0, started = time.perf_counter(), self.now()
                s = self.schema(t)
                path = self.cfg.landing_file(t.name, d)
                try:
                    res = extract_table(snap, self.cfg.source_schema, t, s, mode, window, self.cfg.chunk_rows)
                    table = add_extract_metadata(res.table, s, extract_batch_id=batch_id, extract_mode=mode,
                                                 extracted_at=snap.extracted_at, source_file=_rel(self.cfg, path),
                                                 ingestion_date=d)
                    status = extract_status(res.source_rows, table.num_rows)
                    if status == "mismatch":
                        raise IngestError(f"{t.name}: source_rows {res.source_rows} != rows read {table.num_rows}")
                    write_landing(path, table, s)
                    parquet_rows = parquet_row_count(path)
                    status = extract_status(res.source_rows, parquet_rows)
                    finished = self.now()
                    m = Manifest(1, t.name, batch_id, run_mode, mode, d.isoformat(), iso(window.start), iso(window.end),
                                 iso(window.lower), window.lookback_minutes, res.source_rows, res.rows_in_window,
                                 res.rows_in_lookback, parquet_rows, _rel(self.cfg, path), path.stat().st_size,
                                 sha256_file(path), s.hash, iso(snap.extracted_at), iso(started), iso(finished),
                                 round(time.perf_counter() - t0, 3), "complete" if status == "extracted" else status)
                    write_manifest(path.parent, m)
                    ev = self._event(m, run_mode, None, None, None, status, None, started, finished, t0)
                except Exception as exc:                                       # noqa: BLE001
                    finished = self.now()
                    failures.append(f"{t.name}: {exc}")
                    ev = AuditEvent(batch_id, None, d.isoformat(), t.name, run_mode, mode, iso(window.start),
                                    iso(window.end), iso(window.lower), window.lookback_minutes, None, None, None,
                                    None, None, _rel(self.cfg, path), None, s.hash, None, "failed", str(exc),
                                    iso(started), iso(finished), round(time.perf_counter() - t0, 3))
                    status = "failed"
                events.append(ev)
                outcomes.append(Outcome(t.name, status, [ev]))
        self.write_audit(events)
        if failures:
            raise IngestError("Extraction failed: " + "; ".join(failures))
        return outcomes

    @staticmethod
    def _event(m: Manifest, run_mode: str, load_batch_id, bq_rows, job_id, status, error, started, finished,
               t0) -> AuditEvent:
        return AuditEvent(m.extract_batch_id, load_batch_id, m.business_date, m.table, run_mode,
                          m.extract_mode, m.window_start, m.window_end, m.extract_lower,
                          m.lookback_minutes, m.source_rows, m.rows_in_window, m.rows_in_lookback, m.parquet_rows,
                          bq_rows, m.parquet_file, m.sha256, m.schema_hash, job_id, status, error, iso(started),
                          iso(finished), round(time.perf_counter() - t0, 3))

    # ------------------------------------------------------------------ loading
    def load(self, d: date, tables: list[TableConfig], run_mode: str = "load") -> list[Outcome]:
        bq = self._require_bq()
        load_batch_id = f"load-{d:%Y%m%d}-{_ts_id(self.now())}"
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(lambda t: self._load_one(bq, t, d, load_batch_id, run_mode), tables))
        finally:
            self._cleanup_tmp(load_batch_id)
        self.write_audit([e for o in outcomes for e in o.events])
        failed = [f"{o.table}: {o.message}" for o in outcomes if not passed(o.status)]
        if failed:
            raise IngestError("Load failed: " + "; ".join(failed))
        return outcomes

    def _load_one(self, bq: BigQueryBackend, t: TableConfig, d: date, load_batch_id: str, run_mode: str) -> Outcome:
        t0, started = time.perf_counter(), self.now()
        s = self.schema(t)
        directory = self.cfg.landing_dir(t.name, d)
        m = read_manifest(directory)
        try:
            if m is None:
                raise LandingError(f"no landing artifact for {d} - extract it first")
            path = self.cfg.landing_file(t.name, d)
            verify_landing(path, m, s)                                         # 1. sha256 before
            replay = self._previously_loaded(m)
            tmp = self.cfg.abs(self.cfg.load_tmp_root) / load_batch_id / f"{t.name}.parquet"
            loaded_at = self.now()
            with load_artifact([path], tmp, loaded_at, s) as artifact:         # 2-4. temp artifact (+ _loaded_at)
                res = bq.load_parquet(artifact, partition_target(self.raw_table_id(t), d),
                                      write_disposition="WRITE_TRUNCATE", job_id_prefix=job_id_prefix(t.name, d),
                                      labels={"table": t.name, "business_date": d.strftime("%Y%m%d")})
            if sha256_file(path) != m.sha256:                                  # 7. sha256 after
                raise LandingError(f"{path}: permanent landing file changed during load")
            status = load_status(m.parquet_rows, res.output_rows, replay)
            ev = self._event(m, run_mode, load_batch_id, res.output_rows, res.job_id, status,
                             None if status != "mismatch" else
                             f"parquet_rows {m.parquet_rows} != bq_loaded_rows {res.output_rows}", started, self.now(), t0)
            return Outcome(t.name, status, [ev], ev.error_message or "")
        except Exception as exc:                                               # noqa: BLE001
            ev = AuditEvent(m.extract_batch_id if m else None, load_batch_id, d.isoformat(), t.name, run_mode,
                            m.extract_mode if m else None, m.window_start if m else None, m.window_end if m else None,
                            m.extract_lower if m else None, m.lookback_minutes if m else None,
                            m.source_rows if m else None, m.rows_in_window if m else None,
                            m.rows_in_lookback if m else None, m.parquet_rows if m else None, None,
                            m.parquet_file if m else None, m.sha256 if m else None, s.hash, None, "failed", str(exc),
                            iso(started), iso(self.now()), round(time.perf_counter() - t0, 3))
            return Outcome(t.name, "failed", [ev], str(exc))

    def replay_all(self, tables: list[TableConfig]) -> list[Outcome]:
        """Rebuild each Bronze table from ALL its landing files with one load job (WRITE_TRUNCATE whole table)."""
        bq = self._require_bq()
        load_batch_id = f"replay-all-{_ts_id(self.now())}"
        landing_root = self.cfg.abs(self.cfg.landing_root)
        outcomes, events = [], []
        try:
            self._replay_tables(bq, tables, load_batch_id, landing_root, outcomes, events)
        finally:
            self._cleanup_tmp(load_batch_id)
        self.write_audit(events)
        failed = [f"{o.table}: {o.message}" for o in outcomes if not passed(o.status)]
        if failed:
            raise IngestError("Replay failed: " + "; ".join(failed))
        return outcomes

    def _cleanup_tmp(self, load_batch_id: str) -> None:
        remove_tree(self.cfg.abs(self.cfg.load_tmp_root) / load_batch_id)

    def _replay_tables(self, bq, tables, load_batch_id, landing_root, outcomes, events) -> None:
        for t in tables:
            t0, started = time.perf_counter(), self.now()
            s = self.schema(t)
            manifests, paths = [], []
            try:
                for d in list_landing_dates(landing_root, t.name):
                    m = read_manifest(self.cfg.landing_dir(t.name, d))
                    if m is None:
                        raise LandingError(f"{t.name} dt={d}: landing directory without manifest")
                    p = self.cfg.landing_file(t.name, d)
                    verify_landing(p, m, s)
                    manifests.append(m)
                    paths.append(p)
                if not paths:
                    outcomes.append(Outcome(t.name, "skipped", message="no landing files"))
                    continue
                tmp = self.cfg.abs(self.cfg.load_tmp_root) / load_batch_id / f"{t.name}.parquet"
                with load_artifact(paths, tmp, self.now(), s) as artifact:
                    combined_rows = parquet_row_count(artifact)                # rows actually sent to BigQuery
                    res = bq.load_parquet(artifact, self.raw_table_id(t), write_disposition="WRITE_TRUNCATE",
                                          job_id_prefix=job_id_prefix(t.name, None),
                                          labels={"table": t.name, "business_date": "all"})
                for p, m in zip(paths, manifests):
                    if sha256_file(p) != m.sha256:
                        raise LandingError(f"{p}: permanent landing file changed during load")
                expected = sum(m.parquet_rows for m in manifests)
                if combined_rows != expected:
                    raise LandingError(f"{t.name}: combined artifact has {combined_rows} rows, manifests say {expected}")
                ok = res.output_rows == combined_rows
                # ONE event per table/load job. extract_batch_id is NULL (many extraction batches contributed;
                # each stays traceable through its own manifest and extract audit row). bq_loaded_rows is the
                # job's real output_rows - never a per-file split of it.
                ev = AuditEvent(
                    extract_batch_id=None, load_batch_id=load_batch_id,
                    business_date=manifests[-1].business_date,                 # last business date covered
                    table_name=t.name, run_mode="replay_all", extract_mode=None,
                    window_start=min(m.window_start for m in manifests),       # coverage of the replay
                    window_end=max(m.window_end for m in manifests),
                    extract_lower=None, lookback_minutes=None,
                    source_rows=sum(m.source_rows for m in manifests),
                    rows_in_window=sum(m.rows_in_window for m in manifests),
                    rows_in_lookback=sum(m.rows_in_lookback for m in manifests),
                    parquet_rows=combined_rows, bq_loaded_rows=res.output_rows,
                    parquet_file=_rel(self.cfg, landing_root / t.name) + "/",  # all dt=*/ files of this table
                    file_sha256=None, schema_hash=s.hash, bq_job_id=res.job_id,
                    status="replayed" if ok else "mismatch",
                    error_message=None if ok else (f"combined parquet_rows {combined_rows} != bq_loaded_rows "
                                                   f"{res.output_rows} ({len(manifests)} landing files)"),
                    started_at=iso(started), finished_at=iso(self.now()),
                    duration_s=round(time.perf_counter() - t0, 3))
                events.append(ev)
                outcomes.append(Outcome(t.name, ev.status, [ev],
                                        f"{len(manifests)} landing files, {res.output_rows} rows"))
            except Exception as exc:                                           # noqa: BLE001
                last = manifests[-1].business_date if manifests else self.now().date().isoformat()
                ev = AuditEvent(None, load_batch_id, last, t.name, "replay_all", None, None, None,
                                None, None, None, None, None, None, None, None, None, s.hash, None, "failed", str(exc),
                                iso(started), iso(self.now()), round(time.perf_counter() - t0, 3))
                events.append(ev)
                outcomes.append(Outcome(t.name, "failed", [ev], str(exc)))

    # ------------------------------------------------------------------ composite commands
    def run(self, d: date, tables: list[TableConfig], force: bool = False, allow_gap: bool = False,
            load: bool = True) -> list[Outcome]:
        if load:
            self._require_bq()                       # fail fast, before extracting anything
        out = self.extract(d, tables, "incremental", "run", force=force, allow_gap=allow_gap)
        if load:
            out += self.load(d, tables, run_mode="run")
        return out

    def bootstrap(self, as_of: date, tables: list[TableConfig], load: bool = True) -> list[Outcome]:
        if load:
            self._require_bq()
        out = self.extract(as_of, tables, "bootstrap", "bootstrap")
        if load:
            out += self.load(as_of, tables, run_mode="bootstrap")
        return out

    # ------------------------------------------------------------------ reconciliation
    def reconcile_local(self, tables: list[TableConfig], d: date | None = None) -> list[tuple[str, str, bool, str]]:
        """Landing integrity + latest audit outcome per (table, date). No BigQuery cost."""
        audit = read_local(self.cfg.abs(self.cfg.audit_local_path))
        results = []
        landing_root = self.cfg.abs(self.cfg.landing_root)
        for t in tables:
            s = self.schema(t)
            for dt in ([d] if d else list_landing_dates(landing_root, t.name)):
                m = read_manifest(self.cfg.landing_dir(t.name, dt))
                if m is None:
                    results.append((t.name, dt.isoformat(), False, "no manifest"))
                    continue
                try:
                    verify_landing(self.cfg.landing_file(t.name, dt), m, s)
                    msgs, ok = [], m.source_rows == m.parquet_rows
                    msgs.append(f"source={m.source_rows} parquet={m.parquet_rows} "
                                f"(window={m.rows_in_window}, lookback={m.rows_in_lookback})")
                    loads = self._load_events_for(audit, m)
                    if loads:
                        last = loads[-1]
                        if last["run_mode"] == "replay_all":       # one combined job: compare combined counts
                            ok = ok and passed(last["status"]) and last.get("bq_loaded_rows") == last.get("parquet_rows")
                            msgs.append(f"last load {last['status']} via replay-all {last['load_batch_id']} "
                                        f"(combined bq={last.get('bq_loaded_rows')})")
                        else:
                            ok = ok and passed(last["status"]) and last.get("bq_loaded_rows") == m.parquet_rows
                            msgs.append(f"last load {last['status']} bq={last.get('bq_loaded_rows')}")
                    else:
                        msgs.append("not loaded yet")
                    results.append((t.name, dt.isoformat(), ok, "; ".join(msgs)))
                except LandingError as exc:
                    results.append((t.name, dt.isoformat(), False, str(exc)))
        return results

    def reconcile_full(self, tables: list[TableConfig], as_of: date | None = None,
                       max_pk_diff_rows: int = 500_000) -> list[FullCheck]:
        """Source vs. every Bronze version, as of the end of the latest ingested business day.

        Mutable source rows are limited to `cursor < window_end(as_of)`: rows the source has stamped
        later (e.g. a store that opens next month) are not due in Bronze yet.
        """
        bq = self._require_bq()
        landing_root = self.cfg.abs(self.cfg.landing_root)
        if as_of is None:
            dates = [d for t in tables if t.incremental for d in list_landing_dates(landing_root, t.name)]
            if not dates:
                raise IngestError("Nothing ingested yet - run bootstrap first")
            as_of = max(dates)
        cutoff = full_window(as_of, self.cfg.tz).end
        out = []
        with self._connect() as conn, db.snapshot(conn) as snap:
            for t in tables:
                pk = t.primary_key
                where, params = _cutoff(t, cutoff)
                src_rows = int(snap.scalar(*_count_query(self.cfg, t, where, params)))
                src_max = snap.scalar(*_max_query(self.cfg, t, where, params)) if t.cursor_column else None
                fq = f"`{bq.project}.{self.raw_table_id(t)}`"
                key = pk[0] if len(pk) == 1 else f"TO_JSON_STRING(STRUCT({', '.join(pk)}))"
                agg = bq.query(f"SELECT COUNT(DISTINCT {key}) AS n"
                               + (f", MAX({t.cursor_column}) AS m" if t.cursor_column else "") + f" FROM {fq}")[0]
                missing = extra = None
                if len(pk) == 1 and src_rows <= max_pk_diff_rows:
                    src_keys = {r[0] for r in conn.execute(*_pk_query(self.cfg, t, where, params)).fetchall()}
                    bq_keys = {r["k"] for r in bq.query(f"SELECT DISTINCT {pk[0]} AS k FROM {fq}")}
                    missing, extra = len(src_keys - bq_keys), len(bq_keys - src_keys)
                c = compare_full(t.name, src_rows, int(agg["n"]), src_max, agg.get("m"), missing, extra)
                c.note = (c.note + f" (as of {as_of})").strip()
                out.append(c)
        return out

    # ------------------------------------------------------------------ reset
    def reset_dev(self) -> list[str]:
        done = []
        root = self.cfg.abs(self.cfg.landing_root)
        for t in self.cfg.tables:
            remove_tree(root / t.name)
        done.append(f"removed landing artifacts under {self.cfg.landing_root}")
        for p in (self.cfg.abs(self.cfg.load_tmp_root), self.cfg.abs(self.cfg.audit_local_path).parent):
            remove_tree(p)
        done.append("removed local audit log and temporary load artifacts")
        if self.bq is not None:
            for t in self.cfg.tables:
                self.bq.delete_table(self.raw_table_id(t))
            self.bq.delete_table(self.audit_table_id)
            done.append("dropped Bronze and audit tables")
            done += self.init()
        return done


def _rel(cfg: IngestConfig, path: Path) -> str:
    return path.resolve().relative_to(cfg.repo_root.resolve()).as_posix()


def _cutoff(t: TableConfig, cutoff: datetime):
    from psycopg import sql
    if not t.cursor_column:
        return sql.SQL(""), {}
    return sql.SQL(" WHERE {} < %(cutoff)s").format(sql.Identifier(t.cursor_column)), {"cutoff": cutoff}


def _count_query(cfg: IngestConfig, t: TableConfig, where=None, params=None):
    from psycopg import sql
    return (sql.SQL("SELECT count(*) FROM {}{}").format(sql.Identifier(cfg.source_schema, t.name),
                                                        where or sql.SQL("")), params or {})


def _max_query(cfg: IngestConfig, t: TableConfig, where=None, params=None):
    from psycopg import sql
    return (sql.SQL("SELECT max({}) FROM {}{}").format(sql.Identifier(t.cursor_column),
                                                       sql.Identifier(cfg.source_schema, t.name),
                                                       where or sql.SQL("")), params or {})


def _pk_query(cfg: IngestConfig, t: TableConfig, where=None, params=None):
    from psycopg import sql
    return (sql.SQL("SELECT {} FROM {}{}").format(sql.Identifier(t.primary_key[0]),
                                                  sql.Identifier(cfg.source_schema, t.name),
                                                  where or sql.SQL("")), params or {})
