#!/usr/bin/env bash
# BeanFlow DEV loop: for each business day D, in this exact order:
#     simulate D  ->  ingest D  ->  next D
# so every intermediate source state (price/cost changes, store moves, refunds, tier upgrades)
# is captured in its own landing partition. Never simulate several days first and ingest afterwards.
#
# Usage:  scripts/dev_loop.sh START DAYS [MODE]
#   START  first business day (YYYY-MM-DD); bootstrap must exist for START-1 (make dev-bootstrap)
#   DAYS   number of days
#   MODE   run      (default) simulate -> extract + load to BigQuery each day
#          extract  simulate -> extract only (fast path); then: python -m beanflow_ingest.cli load --replay-all
#
# Safe to re-run: the simulator skips existing days and ingestion replays completed landing files.
set -euo pipefail

START="${1:?usage: dev_loop.sh START DAYS [run|extract]}"
DAYS="${2:?usage: dev_loop.sh START DAYS [run|extract]}"
MODE="${3:-run}"
case "$MODE" in run|extract) ;; *) echo "MODE must be run or extract" >&2; exit 2 ;; esac

cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"

dates=$("$PY" -c 'import sys, datetime as dt
s = dt.date.fromisoformat(sys.argv[1])
print("\n".join(str(s + dt.timedelta(days=i)) for i in range(int(sys.argv[2]))))' "$START" "$DAYS")
prev=$("$PY" -c 'import sys, datetime as dt; print(dt.date.fromisoformat(sys.argv[1]) - dt.timedelta(days=1))' "$START")

if [ ! -f "data/landing/orders/dt=${prev}/_manifest.json" ]; then
  echo "No landing artifact for ${prev} (the day before START)." >&2
  echo "First run:  make dev-bootstrap START=${START}" >&2
  exit 1
fi

for D in $dates; do
  echo "=== ${D}: simulate"
  "$PY" -m beanflow_sim.cli daily --date "$D"
  echo "=== ${D}: ingest (${MODE})"
  "$PY" -m beanflow_ingest.cli "$MODE" --date "$D"
done
echo "=== done: ${DAYS} day(s) from ${START} (${MODE})"
[ "$MODE" = "extract" ] && echo "Next: ${PY} -m beanflow_ingest.cli load --replay-all"
exit 0
