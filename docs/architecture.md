# BeanFlow Coffee — Data Platform Architecture

## Overview

BeanFlow Coffee is an end-to-end retail analytics portfolio project that simulates a multi-store coffee business.

The project demonstrates both Data Engineering and Data Analytics workflows, including:

- synthetic transaction generation
- PostgreSQL operational source modeling
- incremental Python EL pipelines
- Parquet landing
- BigQuery Bronze storage
- dbt transformations
- dimensional modeling
- analytics marts
- Metabase dashboards
- data quality testing and reconciliation

All business and customer data used in this project is synthetic.

## High-Level Architecture

PostgreSQL
→ Python EL
→ Parquet Landing
→ BigQuery Bronze
→ dbt Silver
→ dbt Intermediate
→ dbt Gold
→ Analytics Marts
→ Metabase

## PostgreSQL Source

PostgreSQL 16 represents the operational POS source.

Source tables include:

- regions
- areas
- stores
- product_categories
- products
- customers
- promotions
- orders
- order_items
- payments

Mutable records can change over time, allowing incremental ingestion and historical reconstruction.

## Synthetic Data Simulator

A Python simulator generates synthetic retail activity for approximately 120 stores across 4 regions and 12 areas.

It generates products, customers, promotions, orders, order items, and payments without using real customer or company data.

## Python EL Pipeline

Python extracts data from PostgreSQL and loads it through the landing and warehouse layers.

The pipeline supports:

- full extraction
- incremental extraction
- mutable tables
- overlapping extraction windows
- replay-safe ingestion
- extraction metadata
- batch tracking

Incremental tables use updated_at timestamps.

Overlapping extraction windows help capture recently changed or late-arriving records. Replay duplicates are resolved in Silver.

## Parquet Landing Layer

Extracted data is written to local Parquet before BigQuery loading.

Example layout:

data/landing/orders/dt=2026-10-01/part-000.parquet

The landing layer provides durable local extraction history and separates extraction from warehouse loading.

## BigQuery Bronze

Raw data is loaded to:

raw_pos

Bronze preserves source columns, historical source versions, ingestion metadata, and overlapping extraction results.

Final business-level deduplication is intentionally deferred to the transformation layer.

## dbt Transformation Layers

Transformation flow:

Bronze
→ Silver
→ Intermediate
→ Gold
→ Analytics Marts

## Silver Layer

Silver standardizes Bronze data and removes ingestion-level duplicates.

For mutable tables, source-version identity is:

primary key + updated_at

This preserves genuinely different historical versions while collapsing duplicate copies caused by overlapping extracts.

## Intermediate Layer

Reusable intermediate models include:

- int_product_versions
- int_store_versions
- int_store_calendar
- int_store_daily_orders
- int_store_daily_items

The layer handles historical intervals, calendar spines, and reusable aggregations.

## Historical Modeling

dim_product uses SCD Type 2.

dim_store uses SCD Type 2.

dim_customer uses SCD Type 1.

SCD2 validity intervals use:

valid_from = updated_at
valid_to = next updated_at

Historical facts use point-in-time joins so product cost and store attributes are resolved as of the transaction timestamp.

## Gold Dimensions

Core dimensions:

- dim_store
- dim_product
- dim_customer
- dim_promotion
- dim_date
- dim_time

dim_store grain: one row per historical store version.

dim_product grain: one row per historical product version.

dim_customer grain: one row per customer.

## Gold Facts

### fct_orders

Grain: one row per latest order.

### fct_order_items

Grain: one row per latest order item.

Includes historical product cost and gross margin.

### fct_payments

Grain: one row per latest payment.

### fct_store_daily_sales

Grain: store × business date.

This is the authoritative store-level KPI fact.

A store-day calendar spine preserves eligible open stores even when they have zero sales.

## Sales Business Rule

Realized sales use:

order_status = completed

Cancelled and refunded orders are excluded.

## KPI Definitions

ADS = Total Sales / Open Store-Days

ADQ = Product Quantity / Open Store-Days

AOV = Total Sales / Transaction Count

Gross Margin = Item Sales - Product Cost

Gross Margin % = Gross Margin / Item Sales

Aggregated ratios are recalculated from their numerator and denominator rather than averaged from lower-grain ratios.

## Analytics Marts

Business-facing marts:

- executive_daily
- store_performance
- product_performance
- customer_cohorts
- customer_rfm

executive_daily grain: one row per business date.

store_performance grain: store × business date.

product_performance grain: historical product version × business date.

customer_cohorts supports first-purchase cohorts and non-cumulative monthly retention.

customer_rfm contains one row per purchasing customer and supports Recency, Frequency, Monetary value, and customer segmentation.

## Metabase BI Layer

Metabase runs locally in Docker and connects to BigQuery using a dedicated read-only service account.

Dashboards include:

- BeanFlow Coffee — Executive Overview
- BeanFlow Coffee — Store Performance
- BeanFlow Coffee — Product & Customer Analytics

The Product & Customer dashboard contains Product Performance, Customer Retention, and Customer RFM tabs.

## Data Quality

Validation includes:

- source constraints
- schema checks
- ingestion validation
- replay deduplication
- uniqueness
- source-version uniqueness
- not-null tests
- relationships
- accepted values
- SCD interval validation
- metric reconciliation

Final dbt validation:

15 table models
15 view models
239 data tests

PASS=269
WARN=0
ERROR=0
SKIP=0
TOTAL=269

## Technology Stack

- PostgreSQL 16
- Python
- Parquet
- Google BigQuery
- dbt Core
- Dimensional / Star Schema modeling
- Metabase
- Docker / Docker Compose
- Git / GitHub
- Google Cloud IAM

## Design Principles

1. Preserve source history before business transformation.
2. Separate ingestion from analytics logic.
3. Define model grain explicitly.
4. Recalculate non-additive ratios from additive components.
5. Preserve zero-activity store-days in KPI denominators.
6. Use point-in-time joins for historical dimensions.
7. Centralize reusable transformation logic.
8. Expose curated models to BI users.
9. Keep credentials and secrets out of version control.
10. Make the platform reproducible through code and documentation.

## End-to-End Flow

Synthetic Retail Data
→ PostgreSQL POS
→ Python Incremental EL
→ Parquet Landing
→ BigQuery Bronze
→ dbt Silver
→ dbt Intermediate
→ dbt Gold
→ Analytics Marts
→ Metabase Dashboards

BeanFlow Coffee demonstrates how operational retail data can be transformed into a tested, historically aware, analytics-ready platform for business reporting and customer analysis.
