"""Command-line interface (`ingest ...` or `python -m beanflow_ingest.cli ...`).

    ingest init                                   create datasets + Bronze/audit tables (idempotent)
    ingest check                                  config, schemas, source drift, BigQuery objects
    ingest bootstrap --as-of D [--tables t ...]   point-in-time snapshot before the first simulated day
    ingest extract  --date D [--tables ...] [--force-reextract] [--allow-gap]
    ingest load     --date D [--tables ...]       replay landing files for D into table$YYYYMMDD
    ingest load     --replay-all [--tables ...]   rebuild Bronze tables from every landing file
    ingest run      --date D [--tables ...]       extract (or reuse) + load + reconcile
    ingest reconcile [--date D] [--tables ...]    landing integrity + audit (local, free)
    ingest reconcile --full [--tables ...]        source vs Bronze (counts, max(updated_at), PK sets)
    ingest reset-dev --yes                        delete landing, audit and Bronze tables (dev only)

Business dates are Asia/Manila calendar days.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from .config import ConfigError, PgSettings, load_config, load_env_file
from .parquet import LandingError
from .runner import IngestError, Outcome, Runner
from .schemas import SchemaDriftError, SchemaError
from .windows import WindowNotClosedError


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {s!r}, expected YYYY-MM-DD") from None


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="tables.yml (default: ingestion/config/tables.yml)")
    common.add_argument("--env-file", type=Path, help=".env file (default: search upwards from the cwd)")
    common.add_argument("--tables", nargs="+", metavar="TABLE", help="limit to these tables")
    common.add_argument("-v", "--verbose", action="store_true")

    p = argparse.ArgumentParser(prog="ingest", description="BeanFlow ingestion: Postgres -> Parquet -> BigQuery")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", parents=[common], help="create BigQuery datasets and tables")
    sub.add_parser("check", parents=[common], help="validate config, schemas, source and BigQuery")
    b = sub.add_parser("bootstrap", parents=[common], help="initial point-in-time snapshot (+ load)")
    b.add_argument("--as-of", type=_date, required=True, help="the day BEFORE the first simulated business day")
    b.add_argument("--no-load", action="store_true", help="write landing files only")
    for name in ("extract", "run"):
        sp = sub.add_parser(name, parents=[common], help=f"{name} one business day")
        sp.add_argument("--date", type=_date, required=True)
        sp.add_argument("--force-reextract", action="store_true",
                        help="replace a completed landing artifact (most recent date only)")
        sp.add_argument("--allow-gap", action="store_true", help="skip the previous-day continuity check")
    ld = sub.add_parser("load", parents=[common], help="load landing files into Bronze (replay)")
    g = ld.add_mutually_exclusive_group(required=True)
    g.add_argument("--date", type=_date)
    g.add_argument("--replay-all", action="store_true")
    rc = sub.add_parser("reconcile", parents=[common], help="reconciliation report")
    rc.add_argument("--date", type=_date)
    rc.add_argument("--full", action="store_true", help="compare source tables with Bronze (BigQuery query)")
    rs = sub.add_parser("reset-dev", parents=[common], help="DESTRUCTIVE: wipe landing, audit and Bronze")
    rs.add_argument("--yes", action="store_true", help="confirm")
    return p


def _bq(cfg):
    if not cfg.gcp_configured:
        return None
    from .bigquery import BigQueryClient
    return BigQueryClient(cfg.gcp_project, cfg.bq_location, cfg.max_query_bytes)


def _print_outcomes(outcomes: list[Outcome]) -> None:
    print(f"{'table':<20}{'step':<10}{'status':<10}{'source':>9}{'window':>9}{'lookback':>9}{'parquet':>9}{'bronze':>9}")
    for o in outcomes:
        if not o.events:
            print(f"{o.table:<20}{'extract':<10}{o.status:<10}  {o.message}")
        for e in o.events:
            step = "load" if e.load_batch_id else "extract"
            f = lambda v: "" if v is None else f"{v:,}"                       # noqa: E731
            print(f"{e.table_name:<20}{step:<10}{e.status:<10}{f(e.source_rows):>9}{f(e.rows_in_window):>9}"
                  f"{f(e.rows_in_lookback):>9}{f(e.parquet_rows):>9}{f(e.bq_loaded_rows):>9}"
                  + (f"  {e.error_message}" if e.error_message else ""))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("beanflow_ingest")
    try:
        load_env_file(args.env_file)
        cfg = load_config(args.config)
        tables = cfg.select(args.tables)
        pg = PgSettings.from_env() if args.command not in ("init", "load") else None
        runner = Runner(cfg, pg, _bq(cfg))

        if args.command == "init":
            for line in runner.init():
                print("ok  ", line)
        elif args.command == "check":
            results = runner.check()
            for item, ok, msg in results:
                print(f"{'ok  ' if ok else 'FAIL'} {item:<40} {msg}")
            return 0 if all(ok for item, ok, _ in results if item != "bigquery") else 1
        elif args.command == "bootstrap":
            _print_outcomes(runner.bootstrap(args.as_of, tables, load=not args.no_load))
        elif args.command == "extract":
            _print_outcomes(runner.extract(args.date, tables, "incremental", "extract",
                                           force=args.force_reextract, allow_gap=args.allow_gap))
        elif args.command == "run":
            _print_outcomes(runner.run(args.date, tables, force=args.force_reextract, allow_gap=args.allow_gap))
        elif args.command == "load":
            _print_outcomes(runner.replay_all(tables) if args.replay_all else runner.load(args.date, tables))
        elif args.command == "reconcile":
            if args.full:
                runner.pg = PgSettings.from_env()
                checks = runner.reconcile_full(tables)
                for c in checks:
                    print(f"{'ok  ' if c.ok else 'FAIL'} {c.table:<20} source={c.source_rows:,} "
                          f"bronze_distinct_pk={c.bronze_distinct_pk:,} max_src={c.source_max_updated_at} "
                          f"max_bronze={c.bronze_max_updated_at} missing={c.missing_in_bronze} "
                          f"extra={c.extra_in_bronze} {c.note}")
                return 0 if all(c.ok for c in checks) else 1
            rows = runner.reconcile_local(tables, args.date)
            for table, d, ok, msg in rows:
                print(f"{'ok  ' if ok else 'FAIL'} {table:<20} {d}  {msg}")
            return 0 if rows and all(r[2] for r in rows) else 1
        elif args.command == "reset-dev":
            if not args.yes:
                log.error("Refusing to reset without --yes (deletes landing files, audit log and Bronze tables).")
                return 2
            for line in runner.reset_dev():
                print("ok  ", line)
            print("Reminder: also reset the source database (python -m beanflow_sim.cli reset --yes) "
                  "so Postgres, landing and Bronze start from the same state.")
    except (ConfigError, SchemaError, SchemaDriftError, LandingError, WindowNotClosedError, IngestError) as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
