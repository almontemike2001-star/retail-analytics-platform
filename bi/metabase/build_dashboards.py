"""Build the BeanFlow Metabase dashboards through the Metabase API (dashboards as code).

Idempotent: on every run it logs in, archives the previous questions/dashboards in the
"BeanFlow Coffee" collection and recreates them on the BigQuery gold marts, then enables
public links (used for screenshots). The original hand-built v1 dashboards are moved once
into an "Archive (v1)" collection; nothing is deleted.

    python bi/metabase/build_dashboards.py      # reads bi/metabase/.env

KPI formulas follow docs/kpi_definitions.md: every ratio is recomputed from its numerator
and denominator at the level shown (never an average of daily ratios).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MB_URL = os.environ.get("MB_URL", "http://localhost:3000")
DB_NAME = "BeanFlow Analytics"
COLLECTION = "BeanFlow Coffee"
ARCHIVE = "Archive (v1)"
V1_PREFIX = "BeanFlow Coffee — "
# Tables are referenced as `dbt_dev_gold.<table>` (default project): Metabase's BigQuery field
# filters qualify columns exactly that way, so a project-qualified FROM breaks the filters.

# Validated colour-blind-safe categorical palette (light mode), assigned in fixed order.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
NO_OTHER = {"graph.max_categories_enabled": True, "graph.max_categories": 50}
# 4-wide KPI tiles are too narrow for ₱5,205,346, and Metabase would compact it to "₱5M".
MILLIONS = {'["name","total_sales"]': {"prefix": "₱", "suffix": "M", "scale": 0.000001, "decimals": 2}}

# --------------------------------------------------------------------------- http


def _env() -> dict[str, str]:
    env = {}
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {**env, **os.environ}


class Metabase:
    def __init__(self, url: str):
        self.url = url
        self.session: str | None = None

    def call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{self.url}/api{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"}
            | ({"X-Metabase-Session": self.session} if self.session else {}),
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path} -> {exc.code}: {exc.read()[:500]!r}") from exc
        return json.loads(raw) if raw else None

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, body or {})

    def put(self, path, body):
        return self.call("PUT", path, body)


def connect(env: dict[str, str]) -> Metabase:
    mb = Metabase(MB_URL)
    mb.session = mb.post(
        "/session", {"username": env["MB_ADMIN_EMAIL"], "password": env["MB_ADMIN_PASSWORD"]}
    )["id"]
    return mb


# --------------------------------------------------------------------------- setup


def database_id(mb: Metabase) -> int:
    dbs = mb.get("/database")
    dbs = dbs.get("data", dbs)
    return next(db["id"] for db in dbs if db["name"] == DB_NAME)


def field_ids(mb: Metabase, db_id: int) -> dict[tuple[str, str], int]:
    meta = mb.get(f"/database/{db_id}/metadata")
    return {
        (t["name"], f["name"]): f["id"]
        for t in meta["tables"]
        if t.get("schema") == "dbt_dev_gold"
        for f in t["fields"]
    }


def collection(mb: Metabase, name: str, color: str = BLUE) -> int:
    for coll in mb.get("/collection"):
        if coll.get("name") == name and not coll.get("archived"):
            return coll["id"]
    return mb.post("/collection", {"name": name, "color": color})["id"]


def archive_v1(mb: Metabase) -> None:
    """Move the hand-built v1 dashboards out of the way (once). Nothing is deleted."""
    archive_id = None
    for dash in mb.get("/dashboard"):
        if dash["name"].startswith(V1_PREFIX) and dash.get("collection_id") is None:
            archive_id = archive_id or collection(mb, ARCHIVE, "#8a8984")
            mb.put(f"/dashboard/{dash['id']}", {"collection_id": archive_id})


def reset_collection(mb: Metabase) -> int:
    coll_id = collection(mb, COLLECTION)
    for item in mb.get(f"/collection/{coll_id}/items")["data"]:
        kind = {"card": "card", "dataset": "card", "dashboard": "dashboard"}.get(item["model"])
        if kind:
            mb.put(f"/{kind}/{item['id']}", {"archived": True})
    return coll_id


# --------------------------------------------------------------------------- builders

PARAMS = {
    "date": {"name": "Business date", "type": "date/all-options", "sectionId": "date"},
    "region": {"name": "Region", "type": "string/=", "sectionId": "string"},
    "area": {"name": "Area", "type": "string/=", "sectionId": "string"},
    "store_type": {"name": "Store type", "type": "string/=", "sectionId": "string"},
    "store": {"name": "Store", "type": "string/=", "sectionId": "string"},
    "category": {"name": "Category", "type": "string/=", "sectionId": "string"},
    "product": {"name": "Product", "type": "string/=", "sectionId": "string"},
    "segment": {"name": "RFM segment", "type": "string/=", "sectionId": "string"},
    "tier": {"name": "Loyalty tier", "type": "string/=", "sectionId": "string"},
    "cohort": {"name": "Cohort month", "type": "date/all-options", "sectionId": "date"},
}


class Builder:
    def __init__(self, mb: Metabase, db_id: int, fields: dict, collection_id: int):
        self.mb, self.db_id, self.fields, self.collection_id = mb, db_id, fields, collection_id
        self.n = 0

    def card(self, name: str, sql: str, display: str, filters: dict[str, tuple], viz=None) -> dict:
        """filters maps a filter key to the (table, column) it filters."""
        tags = {}
        for key, target in filters.items():
            self.n += 1
            tags[key] = {
                "id": f"{key}-{self.n:04d}",
                "name": key,
                "display-name": PARAMS[key]["name"],
                "type": "dimension",
                "dimension": ["field", self.fields[target], None],
                "widget-type": PARAMS[key]["type"],
            }
        if display == "scalar":
            viz = {"scalar.compact_primary_number": False, **(viz or {})}
        card = self.mb.post(
            "/card",
            {
                "name": name,
                "collection_id": self.collection_id,
                "display": display,
                "visualization_settings": viz or {},
                "dataset_query": {
                    "type": "native",
                    "database": self.db_id,
                    "native": {"query": sql.strip(), "template-tags": tags},
                },
            },
        )
        card["_filters"] = list(filters)
        return card

    def dashboard(self, name: str, description: str, params: list[str], layout: list) -> dict:
        dash = self.mb.post(
            "/dashboard",
            {"name": name, "description": description, "collection_id": self.collection_id},
        )
        parameters = [{"id": key, "slug": key, **PARAMS[key]} for key in params]
        dashcards = []
        for i, (item, row, col, sx, sy) in enumerate(layout):
            dc = {"id": -(i + 1), "row": row, "col": col, "size_x": sx, "size_y": sy}
            if isinstance(item, str):  # section heading
                dc |= {
                    "card_id": None,
                    "parameter_mappings": [],
                    "visualization_settings": {
                        "virtual_card": {
                            "name": None,
                            "display": "heading",
                            "visualization_settings": {},
                            "dataset_query": {},
                            "archived": False,
                        },
                        "text": item,
                        "dashcard.background": False,
                    },
                }
            else:
                dc |= {
                    "card_id": item["id"],
                    "parameter_mappings": [
                        {
                            "parameter_id": key,
                            "card_id": item["id"],
                            "target": ["dimension", ["template-tag", key]],
                        }
                        for key in item["_filters"]
                        if key in params
                    ],
                }
            dashcards.append(dc)
        self.mb.put(f"/dashboard/{dash['id']}", {"parameters": parameters, "dashcards": dashcards})
        uuid = self.mb.post(f"/dashboard/{dash['id']}/public_link")["uuid"]
        return {"id": dash["id"], "name": name, "public_url": f"{MB_URL}/public/dashboard/{uuid}"}


def money(*cols: str) -> dict:
    return {f'["name","{c}"]': {"prefix": "₱", "decimals": 0} for c in cols}


def pct(*cols: str, decimals: int = 1) -> dict:
    return {f'["name","{c}"]': {"number_style": "percent", "decimals": decimals} for c in cols}


def dec(*cols: str, decimals: int = 1) -> dict:
    return {f'["name","{c}"]': {"decimals": decimals} for c in cols}


def chart(x, ys, colors, x_title="", y_title="", **extra) -> dict:
    return {
        "graph.dimensions": x if isinstance(x, list) else [x],
        "graph.metrics": ys,
        "graph.x_axis.title_text": x_title,
        "graph.y_axis.title_text": y_title,
        "series_settings": {y: {"color": c} for y, c in zip(ys, colors, strict=True)},
        **extra,
    }


# --------------------------------------------------------------------------- dashboards


def executive(b: Builder) -> dict:
    t = "executive_daily"
    f = {"date": (t, "business_date")}
    src = f"from `dbt_dev_gold.{t}` where {{{{date}}}}"
    kpis = [
        b.card("Total sales", f"select sum(total_sales) as total_sales {src}", "scalar", f,
               {"column_settings": MILLIONS}),
        b.card("Transactions", f"select sum(transaction_count) as transactions {src}", "scalar", f),
        b.card("AOV", f"select safe_divide(sum(total_sales), sum(transaction_count)) as aov {src}",
               "scalar", f, {"column_settings": {'["name","aov"]': {"prefix": "₱", "decimals": 2}}}),
        b.card("ADS",
               f"select safe_divide(sum(total_sales), sum(store_days)) as ads {src}", "scalar", f,
               {"column_settings": money("ads")}),
        b.card("ADQ",
               f"select safe_divide(sum(product_quantity), sum(store_days)) as adq {src}", "scalar", f,
               {"column_settings": dec("adq", decimals=1)}),
        b.card("Gross margin %",
               f"select safe_divide(sum(gross_margin), sum(item_sales)) as gross_margin_rate {src}",
               "scalar", f, {"column_settings": pct("gross_margin_rate")}),
    ]
    daily_sales = b.card(
        "Daily sales",
        f"select business_date, sum(total_sales) as total_sales {src} group by 1 order by 1",
        "line", f,
        chart("business_date", ["total_sales"], [BLUE], "Business date", "Sales (₱)")
        | {"column_settings": money("total_sales")},
    )
    daily_tx = b.card(
        "Daily transactions",
        f"select business_date, sum(transaction_count) as transactions {src} group by 1 order by 1",
        "bar", f, chart("business_date", ["transactions"], [BLUE], "Business date", "Transactions"),
    )
    daily_ads = b.card(
        "Daily ADS",
        f"select business_date, safe_divide(sum(total_sales), sum(store_days)) as ads {src} group by 1 order by 1",
        "line", f,
        chart("business_date", ["ads"], [BLUE], "Business date", "₱ per open store-day")
        | {"column_settings": money("ads")},
    )
    daily_adq = b.card(
        "Daily ADQ",
        f"select business_date, safe_divide(sum(product_quantity), sum(store_days)) as adq {src} group by 1 order by 1",
        "line", f,
        chart("business_date", ["adq"], [BLUE], "Business date", "Units per open store-day")
        | {"column_settings": dec("adq")},
    )
    margin = b.card(
        "Gross margin % by day",
        f"select business_date, safe_divide(sum(gross_margin), sum(item_sales)) as gross_margin_rate {src} group by 1 order by 1",
        "line", f,
        chart("business_date", ["gross_margin_rate"], [BLUE], "Business date", "Gross margin %")
        | {"column_settings": pct("gross_margin_rate")},
    )
    dow = b.card(
        "Sales by day of week",
        f"""select day_name, any_value(day_of_week_number) as dow, sum(total_sales) as total_sales
            {src} group by 1 order by 2""",
        "bar", f,
        chart("day_name", ["total_sales"], [BLUE], "Day of week", "Sales (₱)")
        | {"column_settings": money("total_sales")},
    )
    return b.dashboard(
        "Executive Overview",
        "Headline sales, order and margin KPIs for the BeanFlow chain. Synthetic data.",
        ["date"],
        [
            (kpis[0], 0, 0, 4, 3), (kpis[1], 0, 4, 4, 3), (kpis[2], 0, 8, 4, 3),
            (kpis[3], 0, 12, 4, 3), (kpis[4], 0, 16, 4, 3), (kpis[5], 0, 20, 4, 3),
            (daily_sales, 3, 0, 12, 6), (daily_tx, 3, 12, 12, 6),
            (daily_ads, 9, 0, 12, 6), (daily_adq, 9, 12, 12, 6),
            (margin, 15, 0, 12, 6), (dow, 15, 12, 12, 6),
        ],
    )  # fmt: skip


def stores(b: Builder) -> dict:
    t = "store_performance"
    f = {
        "date": (t, "business_date"),
        "region": (t, "region_name"),
        "area": (t, "area_name"),
        "store_type": (t, "store_type"),
        "store": (t, "store_name"),
    }
    where = "where {{date}} and {{region}} and {{area}} and {{store_type}} and {{store}}"
    src = f"from `dbt_dev_gold.{t}` {where}"
    sd = "count(distinct store_day_key)"
    kpis = [
        b.card("Total sales", f"select sum(total_sales) as total_sales {src}", "scalar", f,
               {"column_settings": MILLIONS}),
        b.card("Transactions", f"select sum(transaction_count) as transactions {src}", "scalar", f),
        b.card("AOV", f"select safe_divide(sum(total_sales), sum(transaction_count)) as aov {src}",
               "scalar", f, {"column_settings": {'["name","aov"]': {"prefix": "₱", "decimals": 2}}}),
        b.card("ADS", f"select safe_divide(sum(total_sales), {sd}) as ads {src}", "scalar", f,
               {"column_settings": money("ads")}),
        b.card("ADQ", f"select safe_divide(sum(product_quantity), {sd}) as adq {src}", "scalar", f,
               {"column_settings": dec("adq")}),
        b.card("Gross margin %",
               f"select safe_divide(sum(gross_margin), sum(item_sales)) as gross_margin_rate {src}",
               "scalar", f, {"column_settings": pct("gross_margin_rate")}),
    ]
    by_region_sales = b.card(
        "Sales by region (raw total)",
        f"select region_name as region, sum(total_sales) as total_sales {src} group by 1 order by 2 desc",
        "row", f,
        chart("region", ["total_sales"], [BLUE], **NO_OTHER)
        | {"column_settings": money("total_sales")},
    )
    by_region_ads = b.card(
        "ADS by region (fair comparison)",
        f"select region_name as region, safe_divide(sum(total_sales), {sd}) as ads {src} group by 1 order by 2 desc",
        "row", f,
        chart("region", ["ads"], [BLUE], **NO_OTHER)
        | {"column_settings": money("ads")},
    )
    top_sales = b.card(
        "Top 10 stores by sales",
        f"select replace(store_name, 'BeanFlow ', '') as store, sum(total_sales) as total_sales {src} group by 1 order by 2 desc limit 10",
        "row", f,
        chart("store", ["total_sales"], [BLUE], **NO_OTHER) | {"column_settings": money("total_sales")},
    )
    top_ads = b.card(
        "Bottom 10 stores by ADS",
        f"select replace(store_name, 'BeanFlow ', '') as store, safe_divide(sum(total_sales), {sd}) as ads {src} group by 1 order by 2 asc limit 10",
        "row", f, chart("store", ["ads"], [BLUE], **NO_OTHER) | {"column_settings": money("ads")},
    )
    by_type = b.card(
        "ADS by store type",
        f"select initcap(replace(store_type, '_', ' ')) as store_type, safe_divide(sum(total_sales), {sd}) as ads {src} group by 1 order by 2 desc",
        "bar", f,
        chart("store_type", ["ads"], [BLUE], "Store type", "₱ per open store-day")
        | {"column_settings": money("ads")},
    )
    margin_region = b.card(
        "Gross margin % by region",
        f"select region_name as region, safe_divide(sum(gross_margin), sum(item_sales)) as gross_margin_rate {src} group by 1 order by 2 desc",
        "row", f,
        chart("region", ["gross_margin_rate"], [BLUE], **NO_OTHER)
        | {"column_settings": pct("gross_margin_rate")},
    )
    trend = b.card(
        "Daily ADS by region",
        f"""select business_date,
                   safe_divide(sum(if(region_name = 'Metro Manila', total_sales, 0)),
                               count(distinct if(region_name = 'Metro Manila', store_day_key, null))) as `Metro Manila`,
                   safe_divide(sum(if(region_name = 'South Luzon', total_sales, 0)),
                               count(distinct if(region_name = 'South Luzon', store_day_key, null))) as `South Luzon`,
                   safe_divide(sum(if(region_name = 'Visayas & Mindanao', total_sales, 0)),
                               count(distinct if(region_name = 'Visayas & Mindanao', store_day_key, null))) as `Visayas & Mindanao`,
                   safe_divide(sum(if(region_name = 'North Luzon', total_sales, 0)),
                               count(distinct if(region_name = 'North Luzon', store_day_key, null))) as `North Luzon`
            {src} group by 1 order by 1""",
        "line", f,
        chart("business_date", ["Metro Manila", "South Luzon", "Visayas & Mindanao", "North Luzon"],
              [BLUE, ORANGE, AQUA, YELLOW], "Business date", "₱ per open store-day"),
    )
    detail = b.card(
        "Store scorecard",
        f"""select replace(store_name, 'BeanFlow ', '') as `Store`, region_name as `Region`, area_name as `Area`,
                   initcap(replace(store_type, '_', ' ')) as `Type`, sum(total_sales) as `Sales`,
                   sum(transaction_count) as `Transactions`,
                   safe_divide(sum(total_sales), sum(transaction_count)) as `AOV`,
                   safe_divide(sum(total_sales), {sd}) as `ADS`,
                   safe_divide(sum(product_quantity), {sd}) as `ADQ`,
                   safe_divide(sum(gross_margin), sum(item_sales)) as `Margin %`
            {src} group by 1, 2, 3, 4 order by `Sales` desc""",
        "table", f,
        {"column_settings": money("Sales", "AOV", "ADS") | dec("ADQ") | pct("Margin %")},
    )
    return b.dashboard(
        "Store Performance",
        "Sales, ADS and ADQ by region, area, store type and store. Synthetic data.",
        ["date", "region", "area", "store_type", "store"],
        [
            (kpis[0], 0, 0, 4, 3), (kpis[1], 0, 4, 4, 3), (kpis[2], 0, 8, 4, 3),
            (kpis[3], 0, 12, 4, 3), (kpis[4], 0, 16, 4, 3), (kpis[5], 0, 20, 4, 3),
            (by_region_sales, 3, 0, 12, 6), (by_region_ads, 3, 12, 12, 6),
            (top_sales, 9, 0, 12, 7), (top_ads, 9, 12, 12, 7),
            (by_type, 16, 0, 12, 6), (margin_region, 16, 12, 12, 6),
            (trend, 22, 0, 24, 7),
            (detail, 29, 0, 24, 10),
        ],
    )  # fmt: skip


def products_customers(b: Builder) -> dict:
    p = "product_performance"
    fp = {"date": (p, "business_date"), "category": (p, "category_name"), "product": (p, "product_name")}
    psrc = f"from `dbt_dev_gold.{p}` where {{{{date}}}} and {{{{category}}}} and {{{{product}}}}"
    r = "customer_rfm"
    fr = {"segment": (r, "customer_segment"), "tier": (r, "loyalty_tier")}
    rsrc = f"from `dbt_dev_gold.{r}` where {{{{segment}}}} and {{{{tier}}}}"
    c = "customer_cohorts"
    fc = {"cohort": (c, "cohort_month")}

    pk = [
        b.card("Units sold", f"select sum(product_quantity) as units {psrc}", "scalar", fp),
        b.card("Product sales", f"select sum(product_sales) as product_sales {psrc}", "scalar", fp,
               {"column_settings": money("product_sales")}),
        b.card("Gross margin %",
               f"select safe_divide(sum(gross_margin), sum(product_sales)) as gross_margin_rate {psrc}",
               "scalar", fp, {"column_settings": pct("gross_margin_rate")}),
        b.card("Average selling price",
               f"select safe_divide(sum(product_sales), sum(product_quantity)) as asp {psrc}", "scalar", fp,
               {"column_settings": {'["name","asp"]': {"prefix": "₱", "decimals": 2}}}),
    ]
    top_sales = b.card(
        "Top 10 products by sales",
        f"select product_name as product, sum(product_sales) as product_sales {psrc} group by 1 order by 2 desc limit 10",
        "row", fp, chart("product", ["product_sales"], [BLUE], **NO_OTHER) | {"column_settings": money("product_sales")},
    )
    top_units = b.card(
        "Top 10 products by units",
        f"select product_name as product, sum(product_quantity) as units {psrc} group by 1 order by 2 desc limit 10",
        "row", fp, chart("product", ["units"], [BLUE], **NO_OTHER),
    )
    cat_sales = b.card(
        "Sales by category",
        f"select category_name as category, sum(product_sales) as product_sales {psrc} group by 1 order by 2 desc",
        "row", fp,
        chart("category", ["product_sales"], [BLUE], **NO_OTHER)
        | {"column_settings": money("product_sales")},
    )
    cat_margin = b.card(
        "Gross margin % by category",
        f"select category_name as category, safe_divide(sum(gross_margin), sum(product_sales)) as gross_margin_rate {psrc} group by 1 order by 2 desc",
        "row", fp,
        chart("category", ["gross_margin_rate"], [BLUE], **NO_OTHER)
        | {"column_settings": pct("gross_margin_rate")},
    )

    ck = [
        b.card("Purchasing customers", f"select count(*) as customers {rsrc}", "scalar", fr),
        b.card("Customer sales", f"select sum(monetary) as customer_sales {rsrc}", "scalar", fr,
               {"column_settings": money("customer_sales")}),
        b.card("Avg spend per customer", f"select avg(monetary) as avg_spend {rsrc}", "scalar", fr,
               {"column_settings": {'["name","avg_spend"]': {"prefix": "₱", "decimals": 0}}}),
        b.card("Avg orders per customer", f"select avg(frequency) as avg_orders {rsrc}", "scalar", fr,
               {"column_settings": dec("avg_orders", decimals=2)}),
    ]
    seg_customers = b.card(
        "Customers by RFM segment",
        f"select customer_segment as segment, count(*) as customers {rsrc} group by 1 order by 2 desc",
        "row", fr, chart("segment", ["customers"], [BLUE], **NO_OTHER),
    )
    seg_sales = b.card(
        "Sales by RFM segment",
        f"select customer_segment as segment, sum(monetary) as customer_sales {rsrc} group by 1 order by 2 desc",
        "row", fr, chart("segment", ["customer_sales"], [BLUE], **NO_OTHER) | {"column_settings": money("customer_sales")},
    )
    months = range(0, 2)  # one week of history spans two calendar months
    cols = ", ".join(
        f"max(if(month_number = {m}, retention_rate, null)) as `M{m}`" for m in months
    )
    cohort = b.card(
        "Cohort retention (share of cohort active)",
        f"""select format_date('%Y-%m', cohort_month) as `Cohort`, max(cohort_size) as `Customers`, {cols}
            from `dbt_dev_gold.{c}` where {{{{cohort}}}} group by 1 order by 1""",
        "table", fc,
        {
            "column_settings": pct(*[f"M{m}" for m in months], decimals=0),
            "table.column_formatting": [
                {
                    "columns": [f"M{m}" for m in months],
                    "type": "range",
                    "colors": ["#ffffff", BLUE],
                    "min_type": "custom", "min_value": 0,
                    "max_type": "custom", "max_value": 1,
                    "operator": "=", "value": "", "color": BLUE, "highlight_row": False,
                    "id": 0,
                }
            ],
        },
    )
    tier = b.card(
        "Customers and spend by loyalty tier",
        f"""select initcap(loyalty_tier) as `Tier`, count(*) as `Customers`, sum(monetary) as `Sales`,
                   avg(monetary) as `Avg spend`, avg(frequency) as `Avg orders`
            {rsrc} group by 1 order by `Sales` desc""",
        "table", fr, {"column_settings": money("Sales", "Avg spend") | dec("Avg orders", decimals=2)},
    )
    return b.dashboard(
        "Product & Customer Analytics",
        "Product mix and margin, RFM segments and cohort retention. Synthetic data.",
        ["date", "category", "product", "segment", "tier", "cohort"],
        [
            ("Products", 0, 0, 24, 1),
            (pk[0], 1, 0, 6, 3), (pk[1], 1, 6, 6, 3), (pk[2], 1, 12, 6, 3), (pk[3], 1, 18, 6, 3),
            (top_sales, 4, 0, 12, 7), (top_units, 4, 12, 12, 7),
            (cat_sales, 11, 0, 12, 7), (cat_margin, 11, 12, 12, 7),
            ("Customers", 18, 0, 24, 1),
            (ck[0], 19, 0, 6, 3), (ck[1], 19, 6, 6, 3), (ck[2], 19, 12, 6, 3), (ck[3], 19, 18, 6, 3),
            (seg_customers, 22, 0, 12, 7), (seg_sales, 22, 12, 12, 7),
            (cohort, 29, 0, 9, 6), (tier, 29, 9, 15, 6),
        ],
    )  # fmt: skip


def main() -> None:
    env = _env()
    mb = connect(env)
    mb.put("/setting/enable-public-sharing", {"value": True})
    db_id = database_id(mb)
    mb.post(f"/database/{db_id}/sync_schema")
    time.sleep(5)
    archive_v1(mb)
    builder = Builder(mb, db_id, field_ids(mb, db_id), reset_collection(mb))
    dashboards = [executive(builder), stores(builder), products_customers(builder)]
    (HERE / "dashboards.json").write_text(json.dumps(dashboards, indent=2) + "\n")
    for dash in dashboards:
        print(f"{dash['name']:<30} {dash['public_url']}")


if __name__ == "__main__":
    main()
