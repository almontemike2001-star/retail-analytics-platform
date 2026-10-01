import pytest
import yaml

from beanflow_ingest.config import ConfigError, load_config

STATIC = {"regions", "areas", "product_categories"}
INCREMENTAL = {"stores", "products", "customers", "promotions", "orders", "order_items", "payments"}


def test_tables_yml_parses(cfg):
    assert {t.name for t in cfg.tables} == STATIC | INCREMENTAL
    for t in cfg.tables:
        if t.name in STATIC:
            assert t.mode == "full" and t.cursor_column is None and t.lookback_minutes == 0
        else:
            assert t.mode == "incremental" and t.cursor_column == "updated_at" and t.lookback_minutes == 60
    assert cfg.table("order_items").cluster_by == ("order_id", "order_item_id")
    assert cfg.table("payments").cluster_by == ("order_id", "payment_id")
    assert cfg.bq_location == "asia-southeast1" and cfg.bq_raw_dataset == "raw_pos"
    assert cfg.bq_audit_dataset == "dq_audit" and cfg.settle_minutes == 5
    assert not cfg.gcp_configured


def test_env_overrides(repo):
    cfg = load_config(repo_root=repo, env={"GCP_PROJECT_ID": "my-proj", "BQ_RAW_DATASET": "raw_dev",
                                           "BQ_LOCATION": "US"})
    assert cfg.gcp_project == "my-proj" and cfg.bq_raw_dataset == "raw_dev" and cfg.bq_location == "US"


def _write(repo, mutate):
    path = repo / "ingestion/config/tables.yml"
    doc = yaml.safe_load(path.read_text())
    mutate(doc)
    path.write_text(yaml.safe_dump(doc))
    return path


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["tables"][0].update(colour="red"), "unknown keys"),
    (lambda d: d["tables"].append(dict(d["tables"][0])), "duplicate"),
    (lambda d: d["tables"][5].pop("cursor_column"), "require cursor_column"),
    (lambda d: d["tables"][0].update(cursor_column="updated_at"), "must not set cursor_column"),
    (lambda d: d["tables"][0].update(mode="cdc"), "mode must be"),
    (lambda d: d["tables"][0].update(schema_file="ingestion/schemas/nope.yml"), "schema_file not found"),
    (lambda d: d["tables"][3].update(cluster_by=["a", "b", "c", "d", "e"]), "at most 4"),
    (lambda d: d["tables"][3].update(lookback_minutes=-5), "lookback_minutes"),
    (lambda d: d["defaults"].update(nonsense=1), "unknown keys"),
    (lambda d: d.update(version=2), "version: 1"),
    (lambda d: d["tables"][0].update(primary_key=[]), "primary_key"),
])
def test_bad_config(repo, mutate, message):
    _write(repo, mutate)
    with pytest.raises(ConfigError, match=message):
        load_config(repo_root=repo, env={})


def test_new_table_is_config_only(repo):
    """Adding a table needs a config entry + schema file, nothing else."""
    (repo / "ingestion/schemas/loyalty_events.yml").write_text(
        "table: loyalty_events\ncolumns:\n  - {name: event_id, type: \"int64\", nullable: false}\n"
        "  - {name: updated_at, type: \"timestamp\", nullable: false}\n")
    _write(repo, lambda d: d["tables"].append({"name": "loyalty_events", "mode": "incremental",
                                                "primary_key": ["event_id"], "cursor_column": "updated_at",
                                                "schema_file": "ingestion/schemas/loyalty_events.yml"}))
    cfg = load_config(repo_root=repo, env={})
    assert cfg.table("loyalty_events").lookback_minutes == 60
