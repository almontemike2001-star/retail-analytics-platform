"""Configuration: tables.yml + environment (.env). Validates strictly and fails fast.

Nothing secret lives here or in tables.yml. PostgreSQL settings come from the
same variables the simulator uses; GCP settings are non-secret identifiers and
authentication uses Application Default Credentials (see docs/setup_gcp.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

PACKAGE_REPO_ROOT = Path(__file__).resolve().parents[2]       # <repo>/ingestion/beanflow_ingest/config.py
DEFAULT_CONFIG_REL = Path("ingestion/config/tables.yml")

MODES = ("full", "incremental")
DEFAULT_KEYS = {
    "source_schema", "business_timezone", "landing_root", "load_tmp_root", "audit_local_path", "file_name",
    "bq_location", "bq_raw_dataset", "bq_audit_dataset", "bq_audit_table", "partition_field",
    "lookback_minutes", "settle_minutes", "chunk_rows", "max_query_bytes",
}
TABLE_KEYS = {"name", "mode", "primary_key", "cursor_column", "cluster_by", "schema_file",
              "lookback_minutes", "bq_table", "enabled"}


class ConfigError(ValueError):
    """Invalid tables.yml or environment."""


# ---------------------------------------------------------------------------
# .env loading (same convention as the simulator; existing env vars win)
# ---------------------------------------------------------------------------
def load_env_file(path: Path | None = None, start: Path | None = None) -> Path | None:
    start = start or Path.cwd()
    candidates = [path] if path else [d / ".env" for d in (start, *start.parents)]
    for c in candidates:
        if c and c.is_file():
            for raw in c.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.split(" #", 1)[0].strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)
            return c
    return None


@dataclass(frozen=True)
class PgSettings:
    host: str
    port: int
    dbname: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "PgSettings":
        names = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
        missing = [n for n in names if not os.environ.get(n)]
        if missing:
            raise ConfigError(f"Missing PostgreSQL settings: {', '.join(missing)} (see .env.example)")
        return cls(os.environ["POSTGRES_HOST"], int(os.environ["POSTGRES_PORT"]), os.environ["POSTGRES_DB"],
                   os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"])

    def connect_kwargs(self, dbname: str | None = None) -> dict:
        return {"host": self.host, "port": self.port, "dbname": dbname or self.dbname, "user": self.user,
                "password": self.password, "application_name": "beanflow-ingest"}

    def __repr__(self) -> str:
        return f"PgSettings(host={self.host!r}, port={self.port}, dbname={self.dbname!r}, user={self.user!r})"


# ---------------------------------------------------------------------------
# tables.yml
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TableConfig:
    name: str
    mode: str
    primary_key: tuple[str, ...]
    schema_file: Path                       # absolute
    cursor_column: str | None = None
    cluster_by: tuple[str, ...] = ()
    lookback_minutes: int = 60
    bq_table: str = ""
    enabled: bool = True

    @property
    def incremental(self) -> bool:
        return self.mode == "incremental"


@dataclass(frozen=True)
class IngestConfig:
    repo_root: Path
    tables: tuple[TableConfig, ...]
    source_schema: str = "pos"
    business_timezone: str = "Asia/Manila"
    landing_root: Path = Path("data/landing")
    load_tmp_root: Path = Path("data/.load_tmp")
    audit_local_path: Path = Path("data/audit/ingestion_log.jsonl")
    file_name: str = "part-000.parquet"
    bq_location: str = "asia-southeast1"
    bq_raw_dataset: str = "raw_pos"
    bq_audit_dataset: str = "dq_audit"
    bq_audit_table: str = "ingestion_log"
    partition_field: str = "_ingestion_date"
    settle_minutes: int = 5
    chunk_rows: int = 50_000
    max_query_bytes: int = 1_000_000_000
    gcp_project: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

    def abs(self, rel: Path) -> Path:
        return rel if rel.is_absolute() else self.repo_root / rel

    def table(self, name: str) -> TableConfig:
        for t in self.tables:
            if t.name == name:
                return t
        raise ConfigError(f"Unknown table {name!r}; configured: {[t.name for t in self.tables]}")

    def select(self, names: list[str] | None) -> list[TableConfig]:
        if not names:
            return [t for t in self.tables if t.enabled]
        return [self.table(n) for n in names]

    def landing_dir(self, table: str, business_date) -> Path:
        return self.abs(self.landing_root) / table / f"dt={business_date.isoformat()}"

    def landing_file(self, table: str, business_date) -> Path:
        return self.landing_dir(table, business_date) / self.file_name

    def rel(self, path: Path) -> str:
        """Repository-relative POSIX path (never leaks the local user's home directory)."""
        return path.resolve().relative_to(self.repo_root.resolve()).as_posix()

    @property
    def gcp_configured(self) -> bool:
        return bool(self.gcp_project)


def _as_tuple(value, key: str, table: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{table}: {key} must be a non-empty list of column names")
    return tuple(value)


def load_config(path: Path | None = None, repo_root: Path | None = None, env: dict | None = None) -> IngestConfig:
    env = os.environ if env is None else env
    repo_root = (repo_root or Path(env.get("BEANFLOW_REPO_ROOT") or PACKAGE_REPO_ROOT)).resolve()
    path = path or repo_root / DEFAULT_CONFIG_REL
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from None
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise ConfigError(f"{path}: expected a mapping with 'version: 1'")
    unknown_top = set(doc) - {"version", "defaults", "tables"}
    if unknown_top:
        raise ConfigError(f"{path}: unknown top-level keys {sorted(unknown_top)}")

    defaults = doc.get("defaults") or {}
    unknown = set(defaults) - DEFAULT_KEYS
    if unknown:
        raise ConfigError(f"defaults: unknown keys {sorted(unknown)}")

    raw_tables = doc.get("tables")
    if not isinstance(raw_tables, list) or not raw_tables:
        raise ConfigError("tables: must be a non-empty list")
    tables, seen = [], set()
    for raw in raw_tables:
        if not isinstance(raw, dict) or "name" not in raw:
            raise ConfigError(f"tables: every entry needs a name (got {raw!r})")
        name = raw["name"]
        unknown = set(raw) - TABLE_KEYS
        if unknown:
            raise ConfigError(f"{name}: unknown keys {sorted(unknown)}")
        if name in seen:
            raise ConfigError(f"{name}: duplicate table entry")
        seen.add(name)
        mode = raw.get("mode")
        if mode not in MODES:
            raise ConfigError(f"{name}: mode must be one of {MODES}, got {mode!r}")
        cursor = raw.get("cursor_column")
        if mode == "incremental" and not cursor:
            raise ConfigError(f"{name}: incremental tables require cursor_column")
        if mode == "full" and cursor:
            raise ConfigError(f"{name}: full tables must not set cursor_column")
        if "schema_file" not in raw:
            raise ConfigError(f"{name}: schema_file is required")
        schema_file = (repo_root / raw["schema_file"]).resolve()
        if not schema_file.is_file():
            raise ConfigError(f"{name}: schema_file not found: {raw['schema_file']}")
        cluster = tuple(raw.get("cluster_by") or ())
        if len(cluster) > 4:
            raise ConfigError(f"{name}: BigQuery allows at most 4 clustering columns")
        lookback = int(raw.get("lookback_minutes", defaults.get("lookback_minutes", 60)))
        if lookback < 0:
            raise ConfigError(f"{name}: lookback_minutes must be >= 0")
        tables.append(TableConfig(
            name=name, mode=mode, primary_key=_as_tuple(raw.get("primary_key"), "primary_key", name),
            schema_file=schema_file, cursor_column=cursor, cluster_by=cluster,
            lookback_minutes=lookback if mode == "incremental" else 0,
            bq_table=raw.get("bq_table", name), enabled=bool(raw.get("enabled", True))))

    def d(key, default):
        return defaults.get(key, default)

    cfg = IngestConfig(
        repo_root=repo_root, tables=tuple(tables),
        source_schema=d("source_schema", "pos"), business_timezone=d("business_timezone", "Asia/Manila"),
        landing_root=Path(env.get("BEANFLOW_LANDING_ROOT") or d("landing_root", "data/landing")),
        load_tmp_root=Path(d("load_tmp_root", "data/.load_tmp")),
        audit_local_path=Path(d("audit_local_path", "data/audit/ingestion_log.jsonl")),
        file_name=d("file_name", "part-000.parquet"),
        bq_location=env.get("BQ_LOCATION") or d("bq_location", "asia-southeast1"),
        bq_raw_dataset=env.get("BQ_RAW_DATASET") or d("bq_raw_dataset", "raw_pos"),
        bq_audit_dataset=env.get("BQ_AUDIT_DATASET") or d("bq_audit_dataset", "dq_audit"),
        bq_audit_table=d("bq_audit_table", "ingestion_log"),
        partition_field=d("partition_field", "_ingestion_date"),
        settle_minutes=int(d("settle_minutes", 5)), chunk_rows=int(d("chunk_rows", 50_000)),
        max_query_bytes=int(d("max_query_bytes", 1_000_000_000)),
        gcp_project=env.get("GCP_PROJECT_ID") or None)
    try:
        cfg.tz
    except Exception:
        raise ConfigError(f"Unknown business_timezone {cfg.business_timezone!r}") from None
    return cfg
