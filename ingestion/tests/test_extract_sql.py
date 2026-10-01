from datetime import date
from zoneinfo import ZoneInfo

import pytest

from beanflow_ingest.extract import build_count, build_select, effective_mode
from beanflow_ingest.schemas import load_schema
from beanflow_ingest.windows import bootstrap_window, full_window, incremental_window

MNL = ZoneInfo("Asia/Manila")


def test_static_tables_are_always_full(cfg):
    assert effective_mode(cfg.table("regions"), "incremental") == "full"
    assert effective_mode(cfg.table("regions"), "bootstrap") == "full"
    assert effective_mode(cfg.table("orders"), "bootstrap") == "bootstrap"
    with pytest.raises(ValueError):
        effective_mode(cfg.table("orders"), "full")


def test_incremental_predicate(cfg):
    t = cfg.table("orders")
    w = incremental_window(date(2026, 7, 3), MNL, 60)
    q, params = build_select("pos", t, load_schema(t.schema_file), "incremental", w)
    text = q.as_string(None)
    assert text.startswith('SELECT "order_id", "order_number"')
    assert 'FROM "pos"."orders" WHERE "updated_at" >= %(extract_lower)s AND "updated_at" < %(window_end)s' in text
    assert text.endswith('ORDER BY "order_id"')
    assert params == {"extract_lower": w.lower, "window_end": w.end}
    cq, cp = build_count("pos", t, "incremental", w)
    assert cq.as_string(None) == ('SELECT count(*) FROM "pos"."orders" WHERE "updated_at" >= %(extract_lower)s '
                                  'AND "updated_at" < %(window_end)s') and cp == params


def test_bootstrap_and_full_predicates(cfg):
    t = cfg.table("customers")
    w = bootstrap_window(date(2026, 7, 2), MNL)
    q, params = build_select("pos", t, load_schema(t.schema_file), "bootstrap", w)
    assert 'WHERE "updated_at" < %(window_end)s ORDER BY "customer_id"' in q.as_string(None)
    assert params == {"window_end": w.end}
    r = cfg.table("regions")
    q, params = build_select("pos", r, load_schema(r.schema_file), "full", full_window(date(2026, 7, 3), MNL))
    assert q.as_string(None) == 'SELECT "region_id", "region_name" FROM "pos"."regions" ORDER BY "region_id"'
    assert params == {}
