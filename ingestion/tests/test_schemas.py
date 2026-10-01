import pyarrow as pa
import pytest

from beanflow_ingest.schemas import SchemaDriftError, SchemaError, load_schema


def test_all_schemas_load_and_align_with_config(cfg):
    for t in cfg.tables:
        s = load_schema(t.schema_file, expected_table=t.name)
        assert set(t.primary_key) <= set(s.names)
        if t.cursor_column:
            assert s.column(t.cursor_column).type == "timestamp"
        assert len(s.hash) == 64


def test_type_mappings(cfg):
    s = load_schema(cfg.table("orders").schema_file)
    arrow = s.landing_arrow_schema()
    assert arrow.field("order_id").type == pa.int64()
    assert arrow.field("subtotal").type == pa.decimal128(12, 2)
    assert arrow.field("order_ts").type == pa.timestamp("us", tz="UTC")
    assert arrow.field("customer_id").nullable                      # Bronze accepts whatever the source sends
    assert [f.name for f in arrow][-5:] == ["_extract_batch_id", "_extract_mode", "_extracted_at",
                                           "_source_file", "_ingestion_date"]
    assert not arrow.field("_ingestion_date").nullable
    assert "_loaded_at" not in arrow.names                           # never in the permanent landing file
    assert s.load_arrow_schema().names[-1] == "_loaded_at"

    bq = {f.name: f for f in s.bq_schema()}
    assert bq["subtotal"].field_type == "NUMERIC" and (bq["subtotal"].precision, bq["subtotal"].scale) == (12, 2)
    assert bq["order_ts"].field_type == "TIMESTAMP" and bq["order_id"].field_type == "INT64"
    assert bq["_loaded_at"].mode == "REQUIRED" and bq["customer_id"].mode == "NULLABLE"
    stores = {f.name: f for f in load_schema(cfg.table("stores").schema_file).bq_schema()}
    assert (stores["latitude"].precision, stores["latitude"].scale) == (9, 6)
    assert stores["opened_date"].field_type == "DATE"


@pytest.mark.parametrize("body, message", [
    ("table: x\ncolumns:\n  - {name: id, type: \"uuid\", nullable: false}\n", "unsupported type"),
    ("table: x\ncolumns:\n  - {name: id, type: \"int64\", nullable: false}\n  - {name: id, type: \"int64\", nullable: false}\n", "duplicate"),
    ("table: x\ncolumns:\n  - {name: Id, type: \"int64\", nullable: false}\n", "invalid column name"),
    ("table: x\ncolumns:\n  - {name: _x, type: \"int64\", nullable: false}\n", "invalid column name"),
    ("table: x\ncolumns:\n  - {name: id, type: \"int64\"}\n", "exactly name, type, nullable"),
    ("table: x\ncolumns:\n  - {name: a, type: \"decimal(2,5)\", nullable: false}\n", "invalid decimal"),
    ("table: x\ncolumns: []\n", "non-empty"),
    ("columns:\n  - {name: id, type: \"int64\", nullable: false}\n", "expected keys"),
    ("table: x\ncolumns:\n  - {name: id, type: \"int64\", nullable: maybe}\n", "nullable"),
    ("table: [unclosed\n", "Cannot read schema"),
])
def test_malformed_schemas(tmp_path, body, message):
    p = tmp_path / "x.yml"
    p.write_text(body)
    with pytest.raises(SchemaError, match=message):
        load_schema(p)


def test_wrong_table_name(cfg):
    with pytest.raises(SchemaError, match="declares table"):
        load_schema(cfg.table("orders").schema_file, expected_table="payments")


def _pg(schema):
    out = []
    for c in schema.columns:
        if c.decimal:
            out.append({"column_name": c.name, "data_type": "numeric", "numeric_precision": c.decimal[0],
                        "numeric_scale": c.decimal[1]})
        else:
            dt = {"int64": "bigint", "string": "character varying", "bool": "boolean", "date": "date",
                  "timestamp": "timestamp with time zone"}[c.type]
            out.append({"column_name": c.name, "data_type": dt, "numeric_precision": None, "numeric_scale": None})
    return out


def test_drift_detection(cfg):
    s = load_schema(cfg.table("orders").schema_file)
    live = _pg(s)
    s.check_source(live)                                                   # exact match passes
    s.check_source([dict(c, data_type="integer") if c["column_name"] == "store_id" else c for c in live])  # widening ok

    with pytest.raises(SchemaDriftError, match="missing column 'tax_amount'"):
        s.check_source([c for c in live if c["column_name"] != "tax_amount"])
    with pytest.raises(SchemaDriftError, match="unexpected column 'loyalty_points'"):
        s.check_source(live + [{"column_name": "loyalty_points", "data_type": "integer",
                                "numeric_precision": None, "numeric_scale": None}])
    with pytest.raises(SchemaDriftError, match="incompatible type for 'subtotal'"):
        s.check_source([dict(c, numeric_scale=4) if c["column_name"] == "subtotal" else c for c in live])
    with pytest.raises(SchemaDriftError, match="incompatible type for 'order_ts'"):
        s.check_source([dict(c, data_type="timestamp without time zone") if c["column_name"] == "order_ts" else c
                        for c in live])
    with pytest.raises(SchemaDriftError, match="incompatible type for 'order_id'"):
        s.check_source([dict(c, data_type="text") if c["column_name"] == "order_id" else c for c in live])
