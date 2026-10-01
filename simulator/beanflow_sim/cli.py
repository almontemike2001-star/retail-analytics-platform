"""Command-line interface.

    python -m beanflow_sim.cli seed [--start-date YYYY-MM-DD]
    python -m beanflow_sim.cli backfill --days 90 [--end-date YYYY-MM-DD]
    python -m beanflow_sim.cli daily [--date YYYY-MM-DD]
    python -m beanflow_sim.cli counts
    python -m beanflow_sim.cli reset --yes

Common options: --profile dev|test, --seed N (or BEANFLOW_SIM_SEED), --env-file PATH.
Business dates are Asia/Manila calendar days. Defaults: backfill ends yesterday;
daily generates yesterday; seed's history start = yesterday - (profile days - 1).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from . import db, runner
from .config import DEFAULT_SEED, DbSettings, get_profile, today_local


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {s!r}, expected YYYY-MM-DD") from None


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default=os.environ.get("BEANFLOW_SIM_PROFILE", "dev"), choices=["dev", "test"])
    common.add_argument("--seed", type=int, default=int(os.environ.get("BEANFLOW_SIM_SEED", DEFAULT_SEED)),
                        help="random seed (default: BEANFLOW_SIM_SEED or 42)")
    common.add_argument("--env-file", type=Path, default=None, help="path to .env (default: search upwards)")
    common.add_argument("-v", "--verbose", action="store_true")

    p = argparse.ArgumentParser(prog="beanflow_sim", description="BeanFlow Coffee synthetic POS data simulator")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seed", parents=[common], help="insert master data and base customers (once)")
    s.add_argument("--start-date", type=_date, help="history start date (default: profile.history_days before today)")
    b = sub.add_parser("backfill", parents=[common], help="generate a range of historical days")
    b.add_argument("--days", type=int, help="number of days (default: profile.history_days)")
    b.add_argument("--end-date", type=_date, help="last day to generate (default: yesterday)")
    d = sub.add_parser("daily", parents=[common], help="generate one business day")
    d.add_argument("--date", type=_date, help="business day (default: yesterday)")
    sub.add_parser("counts", parents=[common], help="print row counts per table")
    r = sub.add_parser("reset", parents=[common], help="TRUNCATE all pos tables (local dev only)")
    r.add_argument("--yes", action="store_true", help="confirm the reset")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("beanflow_sim")
    profile = get_profile(args.profile)
    yesterday = today_local() - timedelta(days=1)

    try:
        settings = DbSettings.from_env(args.env_file)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    log.debug("Connecting with %r", settings)

    with db.connect(settings) as conn:
        try:
            if args.command == "seed":
                start = args.start_date or yesterday - timedelta(days=profile.history_days - 1)
                runner.run_seed(conn, profile, args.seed, start)
            elif args.command in ("backfill", "daily"):
                if args.command == "backfill":
                    last = args.end_date or yesterday
                    first = last - timedelta(days=(args.days or profile.history_days) - 1)
                else:
                    first = last = args.date or yesterday
                days = runner.plan_days(conn, first, last)
                totals = runner.run_days(conn, profile, args.seed, days)
                log.info("Done: %s", ", ".join(f"{v:,} {k}" for k, v in totals.items()))
            elif args.command == "counts":
                for table, n in db.row_counts(conn).items():
                    print(f"{table:<20}{n:>12,}")
            elif args.command == "reset":
                if not args.yes:
                    log.error("Refusing to reset without --yes.")
                    return 2
                db.reset(conn)
                log.info("All pos tables truncated and identities restarted.")
        except runner.GenerationError as exc:
            log.error("%s", exc)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
