import os
import stat
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from beanflow_ingest import parquet as pqm
from beanflow_ingest.parquet import LandingError, Manifest, add_extract_metadata, load_artifact
from beanflow_ingest.schemas import load_schema

UTC = timezone.utc
EXTRACTED = datetime(2026, 7, 4, 1, 0, tzinfo=UTC)


def _orders(cfg, rows):
    s = load_schema(cfg.table("orders").schema_file)
    src = pa.Table.from_pylist(rows, schema=pa.schema(s.source_arrow_fields()))
    return s, add_extract_metadata(src, s, extract_batch_id="ext-inc-20260703-x", extract_mode="incremental",
                                   extracted_at=EXTRACTED, source_file="data/landing/orders/dt=2026-07-03/part-000.parquet",
                                   ingestion_date=date(2026, 7, 3))


def _row(order_id=1, ts=None, subtotal="12345678.99"):
    ts = ts or datetime(2026, 7, 3, 8, 15, 30, 123456, tzinfo=ZoneInfo("Asia/Manila"))
    return {"order_id": order_id, "order_number": f"BF-001-20260703-{order_id:04d}", "store_id": 1,
            "customer_id": None, "promotion_id": None, "order_ts": ts, "order_channel": "takeaway",
            "order_status": "completed", "subtotal": Decimal(subtotal), "discount_amount": Decimal("0.00"),
            "tax_amount": Decimal("1.20"), "total_amount": Decimal("11.20"), "updated_at": ts}


def test_empty_parquet(cfg, tmp_path):
    s, t = _orders(cfg, [])
    p = tmp_path / "dt=2026-07-03" / "part-000.parquet"
    pqm.write_landing(p, t, s)
    assert pqm.parquet_row_count(p) == 0
    assert pq.read_schema(p).equals(s.landing_arrow_schema())


def test_decimal_precision_round_trip(cfg, tmp_path):
    s, t = _orders(cfg, [_row(subtotal="9999999999.99")])
    p = tmp_path / "a.parquet"
    pqm.write_landing(p, t, s)
    back = pq.read_table(p)
    assert back.column("subtotal")[0].as_py() == Decimal("9999999999.99")
    assert back.schema.field("subtotal").type == pa.decimal128(12, 2)
    with pytest.raises(pa.ArrowInvalid):
        _orders(cfg, [_row(subtotal="123456789012.50")])         # 12 integer digits do not fit NUMERIC(12,2)


def test_utc_timestamps(cfg, tmp_path):
    manila = datetime(2026, 7, 3, 0, 0, 0, tzinfo=ZoneInfo("Asia/Manila"))
    s, t = _orders(cfg, [_row(ts=manila)])
    p = tmp_path / "a.parquet"
    pqm.write_landing(p, t, s)
    v = pq.read_table(p).column("order_ts")[0].as_py()
    assert v == datetime(2026, 7, 2, 16, 0, tzinfo=UTC) and v.utcoffset().total_seconds() == 0
    assert pq.read_table(p).column("_extracted_at")[0].as_py() == EXTRACTED


def test_atomic_write_and_read_only(cfg, tmp_path):
    s, t = _orders(cfg, [_row(1), _row(2)])
    p = tmp_path / "dt" / "part-000.parquet"
    pqm.write_landing(p, t, s)
    assert not os.access(p, os.W_OK) or os.geteuid() == 0          # read-only (root ignores permissions)
    assert not (p.stat().st_mode & stat.S_IWUSR)
    before = pqm.sha256_file(p)

    def boom(tmp):
        tmp.write_bytes(b"partial")
        raise OSError("disk full")
    with pytest.raises(OSError):
        pqm._atomic_write(p, boom)
    assert pqm.sha256_file(p) == before                              # original untouched
    assert [x.name for x in p.parent.iterdir()] == ["part-000.parquet"]   # no temp files left


def test_schema_guard_on_write(cfg, tmp_path):
    s, t = _orders(cfg, [_row()])
    with pytest.raises(LandingError):
        pqm.write_landing(tmp_path / "a.parquet", t.drop(["_extract_mode"]), s)


def _manifest(cfg, p, s, rows):
    return Manifest(1, "orders", "ext-inc-20260703-x", "run", "incremental", "2026-07-03", "a", "b", "c", 60,
                    rows, rows, 0, rows, cfg.rel(p) if str(p).startswith(str(cfg.repo_root)) else str(p),
                    p.stat().st_size, pqm.sha256_file(p), s.hash, "x", "x", "x", 0.1, "complete")


def test_manifest_generation_and_sha_validation(cfg, tmp_path):
    s, t = _orders(cfg, [_row(1), _row(2)])
    d = tmp_path / "dt=2026-07-03"
    p = d / "part-000.parquet"
    pqm.write_landing(p, t, s)
    m = _manifest(cfg, p, s, 2)
    pqm.write_manifest(d, m)
    assert pqm.read_manifest(d) == m and pqm.is_complete(d, "part-000.parquet")
    pqm.verify_landing(p, m, s)

    p.chmod(0o644)
    with open(p, "r+b") as f:                                        # tamper one byte
        f.seek(10)
        f.write(b"\x00")
    with pytest.raises(LandingError, match="sha256"):
        pqm.verify_landing(p, m, s)


def test_load_artifact_adds_loaded_at_and_is_cleaned_up(cfg, tmp_path):
    s, t = _orders(cfg, [_row(1), _row(2)])
    p = tmp_path / "landing" / "part-000.parquet"
    pqm.write_landing(p, t, s)
    before = pqm.sha256_file(p)
    tmp = tmp_path / ".load_tmp" / "load-1" / "orders.parquet"
    loaded_at = datetime(2026, 10, 1, 5, 0, tzinfo=UTC)
    with load_artifact([p], tmp, loaded_at, s) as art:
        a = pq.read_table(art)
        assert a.column_names == s.load_arrow_schema().names
        assert set(a.column("_loaded_at").to_pylist()) == {loaded_at}
        assert a.column("_extract_batch_id").to_pylist() == ["ext-inc-20260703-x"] * 2
    assert not tmp.exists()                                          # cleaned up on success
    assert "_loaded_at" not in pq.read_schema(p).names               # permanent file never changes
    assert pqm.sha256_file(p) == before


def test_load_artifact_cleanup_on_failure(cfg, tmp_path):
    s, t = _orders(cfg, [_row(1)])
    p = tmp_path / "landing" / "part-000.parquet"
    pqm.write_landing(p, t, s)
    tmp = tmp_path / ".load_tmp" / "load-2" / "orders.parquet"
    with pytest.raises(RuntimeError):
        with load_artifact([p], tmp, datetime.now(UTC), s):
            assert tmp.exists()
            raise RuntimeError("load failed")
    assert not tmp.exists()
