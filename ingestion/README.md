# BeanFlow ingestion (Phase 3)

PostgreSQL `pos.*` → **immutable Parquet landing zone** → **BigQuery Bronze** (`raw_pos.*`) → **`dq_audit.ingestion_log`**

```
simulate D → ingest D (extract → landing Parquet → temp load artifact → table$YYYYMMDD) → next D
```

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e simulator -e "ingestion[dev]"
# BigQuery: follow docs/setup_gcp.md (gcloud ADC, no key files), set GCP_PROJECT_ID in .env
python -m beanflow_ingest.cli init       # datasets raw_pos + dq_audit (asia-southeast1) and all tables
python -m beanflow_ingest.cli check      # config, schemas vs. live Postgres, BigQuery objects, freshness
```

## Commands

| Command | What it does |
| --- | --- |
| `init` | Create datasets and Bronze/audit tables from the explicit schemas (idempotent) |
| `check` | Validate tables.yml, schema files, source schema drift, BigQuery tables, "Bronze not ahead of source" |
| `bootstrap --as-of D [--tables …] [--no-load]` | Point-in-time snapshot of the seeded source as of the day **before** the first simulated day |
| `extract --date D [--tables …]` | Postgres → landing files for business day D (no BigQuery needed) |
| `load --date D [--tables …]` | Landing files for D → `raw_pos.<table>$YYYYMMDD` (WRITE_TRUNCATE) |
| `load --replay-all [--tables …]` | Rebuild each Bronze table from every landing file (one load job per table) |
| `run --date D [--tables …]` | `extract` (or reuse a completed artifact) + `load` |
| `reconcile [--date D]` | Landing integrity (sha256, counts) + latest load outcome, from local files (free) |
| `reconcile --full` | Source `COUNT(*)` vs Bronze distinct PKs, `MAX(updated_at)`, PK set difference |
| `reset-dev --yes` | **Destructive**: delete landing files, local audit, Bronze + audit tables, then re-init |

Options: `--force-reextract` (most recent extracted date only), `--allow-gap`, `--tables`, `--env-file`, `-v`.

DEV loop (from the repository root):

```bash
make dev-bootstrap START=2026-07-03            # seed simulator + bootstrap as of 2026-07-02
make dev-loop START=2026-07-03 DAYS=7          # simulate D -> ingest D, one day at a time
make dev-loop START=2026-07-03 DAYS=90 MODE=extract && python -m beanflow_ingest.cli load --replay-all
make dev-reset CONFIRM=yes                     # Postgres pos data + landing + audit + Bronze, together
```

## Tables

| Mode | Tables | Predicate |
| --- | --- | --- |
| full | regions, areas, product_categories | none (whole table every run) |
| bootstrap | the 7 mutable tables | `updated_at < window_end(as_of)` |
| incremental | stores, products, customers, promotions, orders, order_items, payments | `updated_at >= extract_lower AND updated_at < window_end` |

Configuration: `config/tables.yml`. Schemas: `schemas/<table>.yml` (one definition generates the Postgres
expectations, the PyArrow schema and the BigQuery schema). **Adding a table = one config entry + one schema
file.** Missing/unexpected/incompatible columns fail before any row is extracted.

## Windows (business day D, Asia/Manila → UTC)

```
window_start  = D 00:00 Asia/Manila          inclusive     e.g. 2026-07-03 → 2026-07-02T16:00Z
window_end    = (D+1) 00:00 Asia/Manila      exclusive          → 2026-07-03T16:00Z
extract_lower = window_start - 60 minutes                          → 2026-07-02T15:00Z
```

Extraction is refused until `window_end` is at least 5 minutes in the past. Incremental extraction of D
requires a complete landing artifact for D-1 (`--allow-gap` overrides). All tables of one run are read from one
`REPEATABLE READ READ ONLY` snapshot.

## Landing zone (permanent, immutable)

```
data/landing/<table>/dt=YYYY-MM-DD/part-000.parquet     source columns + _extract_batch_id, _extract_mode,
                                                        _extracted_at, _source_file, _ingestion_date
data/landing/<table>/dt=YYYY-MM-DD/_manifest.json       batch id, window, counts, size, sha256, schema hash, timing, status
```

Written to a temp file, fsynced, renamed into place, then made read-only. `_loaded_at` is **never** in the
landing file.

## Loading and replay

1. verify the landing sha256 against the manifest
2. read the permanent Parquet, add a constant `_loaded_at` (actual UTC load time)
3. write the temporary artifact `data/.load_tmp/<load_batch_id>/<table>.parquet`
4. BigQuery load job (Parquet, explicit schema, `CREATE_NEVER`) into `raw_pos.<table>$YYYYMMDD`, `WRITE_TRUNCATE`
5. delete the temporary artifact (always, also on failure)
6. verify the landing sha256 again

| Identifier | Created by | On replay |
| --- | --- | --- |
| `_extract_batch_id` | extraction (inside the landing file) | preserved |
| `load_batch_id` | every load (audit log only, never in Bronze rows) | new |
| `_loaded_at` | every load (temporary artifact) | new |

A normal rerun of a completed date **replays** its landing file. Re-extracting older dates is blocked because the
mutable source no longer holds those intermediate versions.

## Bronze version semantics (input to Phase 4)

* Bronze is append-only history and is **not deduplicated** during ingestion.
* **Source version identity (incremental tables) = primary key + `updated_at`.**
* The 60-minute lookback (and the bootstrap/day-1 overlap) means the same version can appear in two adjacent
  `_ingestion_date` partitions. That is the same version seen twice, not a new state.
* Phase 4 Silver must first deduplicate on (primary key, `updated_at`) and only then pick the current row or
  build SCD2 history (`dim_store`, `dim_product` are rebuilt from these versions; no dbt snapshots).

## Audit: `dq_audit.ingestion_log`

One row per extraction / load / table event, appended with load jobs (also mirrored to
`data/audit/ingestion_log.jsonl`). Extraction passes when `source_rows = parquet_rows`; loading passes when
`parquet_rows = bq_loaded_rows`. For incremental tables these are **versions changed in the window** (split
into `rows_in_window` and `rows_in_lookback`), not table sizes; use `reconcile --full` for table-level checks.

**`load --replay-all`** runs ONE combined load job per table and writes ONE audit row per table/job:
`extract_batch_id` = NULL (many extraction batches contributed; each stays traceable through its landing
manifest and its own extract audit row), `parquet_rows` = combined landing rows, `bq_loaded_rows` = the job's
actual `output_rows`, `bq_job_id` = that job, `window_start`/`window_end` = the coverage of all files,
`business_date` = the last business date covered, `parquet_file` = `data/landing/<table>/`,
`file_sha256` = NULL, status `replayed` (counts equal) or `mismatch`. No per-file load counts are invented.

## Reset procedure

Postgres, landing files and Bronze must always be reset **together** (`make dev-reset CONFIRM=yes`): the source
restarts its identity sequences, so leftover Bronze rows would collide with a new simulation. `check` reports
"Bronze holds data newer than the source" if they drift apart.

## Tests

```bash
cd ingestion && pytest                    # unit + mocked BigQuery; Postgres integration tests auto-skip if unreachable
pytest -m integration                     # only the Postgres integration tests (database beanflow_ingest_test)
GCP_PROJECT_ID=<p> pytest -m bigquery     # optional live BigQuery test (creates and deletes temp datasets)
```
