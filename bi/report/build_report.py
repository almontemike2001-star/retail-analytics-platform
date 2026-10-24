"""Render the static BeanFlow KPI report (docs/kpi_report.html) from the BigQuery gold marts.

The page is self-contained: query results are embedded as JSON, so GitHub Pages can serve it
without any access to BigQuery. KPI formulas follow docs/kpi_definitions.md (ratios are
recomputed from numerators and denominators, never averaged).

    make report        # or: python bi/report/build_report.py [--out docs/kpi_report.html]

Auth uses Application Default Credentials and GCP_PROJECT_ID from the repo's .env.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from google.cloud import bigquery

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GOLD = "dbt_dev_gold"

QUERIES = {
    "kpis": f"""
        select sum(total_sales) as total_sales, sum(transaction_count) as transactions,
               safe_divide(sum(total_sales), sum(transaction_count)) as aov,
               safe_divide(sum(total_sales), sum(store_days)) as ads,
               safe_divide(sum(product_quantity), sum(store_days)) as adq,
               safe_divide(sum(gross_margin), sum(item_sales)) as gross_margin_rate,
               sum(product_quantity) as units, sum(store_days) as store_days,
               min(business_date) as first_day, max(business_date) as last_day,
               count(*) as business_days
        from {GOLD}.executive_daily
    """,
    "network": f"""
        select count(distinct store_id) as stores, count(distinct region_name) as regions
        from {GOLD}.store_performance
    """,
    "customers": f"""
        select count(*) as customers, avg(monetary) as avg_spend, avg(frequency) as avg_orders
        from {GOLD}.customer_rfm
    """,
    "daily": f"""
        select business_date as day, sum(total_sales) as sales, sum(transaction_count) as transactions,
               safe_divide(sum(total_sales), sum(store_days)) as ads,
               safe_divide(sum(product_quantity), sum(store_days)) as adq
        from {GOLD}.executive_daily group by 1 order by 1
    """,
    "regions": f"""
        select region_name as region, sum(total_sales) as sales,
               count(distinct store_day_key) as store_days,
               safe_divide(sum(total_sales), count(distinct store_day_key)) as ads,
               safe_divide(sum(product_quantity), count(distinct store_day_key)) as adq
        from {GOLD}.store_performance group by 1 order by sales desc
    """,
    "region_daily": f"""
        select business_date as day, region_name as region,
               safe_divide(sum(total_sales), count(distinct store_day_key)) as ads
        from {GOLD}.store_performance group by 1, 2 order by 1, 2
    """,
    "top_stores": f"""
        select replace(store_name, 'BeanFlow ', '') as store, region_name as region,
               initcap(replace(store_type, '_', ' ')) as type, sum(total_sales) as sales,
               safe_divide(sum(total_sales), count(distinct store_day_key)) as ads
        from {GOLD}.store_performance group by 1, 2, 3 order by sales desc limit 10
    """,
    "store_types": f"""
        select initcap(replace(store_type, '_', ' ')) as type, count(distinct store_id) as stores,
               safe_divide(sum(total_sales), count(distinct store_day_key)) as ads
        from {GOLD}.store_performance group by 1 order by ads desc
    """,
    "categories": f"""
        select category_name as category, sum(product_sales) as sales, sum(product_quantity) as units,
               safe_divide(sum(gross_margin), sum(product_sales)) as margin
        from {GOLD}.product_performance group by 1 order by sales desc
    """,
    "rfm": f"""
        select customer_segment as segment, count(*) as customers, sum(monetary) as sales
        from {GOLD}.customer_rfm group by 1 order by customers desc
    """,
}


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def _env_project() -> str:
    env_file = ROOT / ".env"
    if "GCP_PROJECT_ID" not in os.environ and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GCP_PROJECT_ID="):
                return line.split("=", 1)[1].strip()
    return os.environ["GCP_PROJECT_ID"]


def collect() -> dict[str, list[dict]]:
    client = bigquery.Client(project=_env_project())
    return {
        name: [{k: _jsonable(v) for k, v in row.items()} for row in client.query(sql).result()]
        for name, sql in QUERIES.items()
    }


def region_insight(regions: list[dict]) -> str:
    """Point out where ranking by raw sales and by ADS disagree."""
    by_sales = [r["region"] for r in regions]
    by_ads = [r["region"] for r in sorted(regions, key=lambda r: r["ads"], reverse=True)]
    for i, a in enumerate(by_sales):
        for b in by_sales[i + 1 :]:
            if by_ads.index(b) < by_ads.index(a):
                return (
                    f"{a} sells more than {b} in total, but only because it has more store-days. "
                    f"Per open store-day, {b} is ahead. Normalizing changes the ranking."
                )
    return "Raw totals and ADS rank the regions the same way."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "kpi_report.html"))
    args = parser.parse_args()
    data = collect()
    data["region_insight"] = region_insight(data["regions"])
    html = (HERE / "report_template.html").read_text().replace("__DATA__", json.dumps(data))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"report written to {out}")


if __name__ == "__main__":
    main()
