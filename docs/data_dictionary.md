# BeanFlow Coffee — Data Dictionary

## Overview

This data dictionary documents the dbt models that power the BeanFlow Coffee analytics platform.

The model and column inventory is generated from dbt `manifest.json` and `catalog.json`, so the documented schema reflects the actual dbt project and warehouse metadata.

```text
BigQuery Bronze
    ↓
Silver / Staging
    ↓
Intermediate
    ↓
Gold Facts & Dimensions
    ↓
Analytics Marts
    ↓
Metabase
```

---

## Modeling Conventions

- Mutable source versions are preserved using primary key + `updated_at`.
- `dim_product` and `dim_store` use SCD Type 2 history.
- `dim_customer` uses SCD Type 1 latest-state behavior.
- `fct_store_daily_sales` is the authoritative denominator-complete store-day fact.
- Realized sales are based on completed orders.
- AOV, ADS, ADQ, and Gross Margin % are recalculated from their components.

---

# Silver / Staging Models

## `stg_areas`

**Model type:** Staging

**Grain:** one row per source area

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `area_id` | `INT64` | — |
| `region_id` | `INT64` | — |
| `area_name` | `STRING` | — |

---

## `stg_customers`

**Model type:** Staging

**Grain:** one row per preserved customer source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `customer_id` | `INT64` | — |
| `full_name` | `STRING` | — |
| `email` | `STRING` | — |
| `phone` | `STRING` | — |
| `birth_date` | `DATE` | — |
| `gender` | `STRING` | — |
| `city` | `STRING` | — |
| `signup_date` | `DATE` | — |
| `signup_store_id` | `INT64` | — |
| `loyalty_tier` | `STRING` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_order_items`

**Model type:** Staging

**Grain:** one row per preserved order-item source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `order_item_id` | `INT64` | — |
| `order_id` | `INT64` | — |
| `product_id` | `INT64` | — |
| `quantity` | `INT64` | — |
| `unit_price` | `NUMERIC` | — |
| `line_discount` | `NUMERIC` | — |
| `line_total` | `NUMERIC` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_orders`

**Model type:** Staging

**Grain:** one row per preserved order source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `order_id` | `INT64` | — |
| `order_number` | `STRING` | — |
| `store_id` | `INT64` | — |
| `customer_id` | `INT64` | — |
| `promotion_id` | `INT64` | — |
| `order_ts` | `TIMESTAMP` | — |
| `order_channel` | `STRING` | — |
| `order_status` | `STRING` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_amount` | `NUMERIC` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_payments`

**Model type:** Staging

**Grain:** one row per preserved payment source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `payment_id` | `INT64` | — |
| `order_id` | `INT64` | — |
| `payment_method` | `STRING` | — |
| `amount` | `NUMERIC` | — |
| `payment_status` | `STRING` | — |
| `paid_at` | `TIMESTAMP` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_product_categories`

**Model type:** Staging

**Grain:** one row per source product category

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `category_id` | `INT64` | — |
| `category_name` | `STRING` | — |
| `category_group` | `STRING` | — |

---

## `stg_products`

**Model type:** Staging

**Grain:** one row per preserved product source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `product_id` | `INT64` | — |
| `category_id` | `INT64` | — |
| `sku` | `STRING` | — |
| `product_name` | `STRING` | — |
| `size` | `STRING` | — |
| `base_price` | `NUMERIC` | — |
| `unit_cost` | `NUMERIC` | — |
| `is_active` | `BOOL` | — |
| `launched_date` | `DATE` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_promotions`

**Model type:** Staging

**Grain:** one row per preserved promotion source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `promotion_id` | `INT64` | — |
| `promo_code` | `STRING` | — |
| `promo_name` | `STRING` | — |
| `promo_type` | `STRING` | — |
| `discount_value` | `NUMERIC` | — |
| `min_order_amount` | `NUMERIC` | — |
| `start_date` | `DATE` | — |
| `end_date` | `DATE` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

## `stg_regions`

**Model type:** Staging

**Grain:** one row per source region

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `region_id` | `INT64` | — |
| `region_name` | `STRING` | — |

---

## `stg_stores`

**Model type:** Staging

**Grain:** one row per preserved store source version

**Purpose:** Standardized and replay-deduplicated representation of the corresponding Bronze source.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_id` | `INT64` | — |
| `area_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `latitude` | `NUMERIC` | — |
| `longitude` | `NUMERIC` | — |
| `opened_date` | `DATE` | — |
| `closed_date` | `DATE` | — |
| `status` | `STRING` | — |
| `updated_at` | `TIMESTAMP` | — |
| `_extract_batch_id` | `STRING` | — |
| `_extract_mode` | `STRING` | — |
| `_extracted_at` | `TIMESTAMP` | — |
| `_source_file` | `STRING` | — |
| `_ingestion_date` | `DATE` | — |
| `_loaded_at` | `TIMESTAMP` | — |

---

# Intermediate Models

## `int_product_versions`

**Model type:** Intermediate

**Grain:** one row per historical product version

**Purpose:** Reconstructs historical product validity intervals.

| Column | Warehouse Type | Description |
|---|---|---|
| `product_id` | `INT64` | — |
| `category_id` | `INT64` | — |
| `sku` | `STRING` | — |
| `product_name` | `STRING` | — |
| `size` | `STRING` | — |
| `base_price` | `NUMERIC` | — |
| `unit_cost` | `NUMERIC` | — |
| `is_active` | `BOOL` | — |
| `launched_date` | `DATE` | — |
| `valid_from` | `TIMESTAMP` | — |
| `valid_to` | `TIMESTAMP` | — |
| `is_current` | `BOOL` | — |

---

## `int_store_calendar`

**Model type:** Intermediate

**Grain:** one row per eligible store × business date

**Purpose:** Builds the eligible store-day calendar spine.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_sk` | `STRING` | — |
| `store_id` | `INT64` | — |
| `area_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `business_date` | `DATE` | — |

---

## `int_store_daily_items`

**Model type:** Intermediate

**Grain:** one row per store × business date

**Purpose:** Aggregates completed item activity and cost to store-day grain.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_id` | `INT64` | — |
| `store_sk` | `STRING` | — |
| `business_date` | `DATE` | — |
| `product_quantity` | `INT64` | — |
| `item_sales` | `NUMERIC` | — |
| `total_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |

---

## `int_store_daily_orders`

**Model type:** Intermediate

**Grain:** one row per store × business date

**Purpose:** Aggregates completed order activity to store-day grain.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_id` | `INT64` | — |
| `store_sk` | `STRING` | — |
| `business_date` | `DATE` | — |
| `transaction_count` | `INT64` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_sales` | `NUMERIC` | — |

---

## `int_store_versions`

**Model type:** Intermediate

**Grain:** one row per historical store version

**Purpose:** Reconstructs historical store validity intervals.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_id` | `INT64` | — |
| `area_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `latitude` | `NUMERIC` | — |
| `longitude` | `NUMERIC` | — |
| `opened_date` | `DATE` | — |
| `closed_date` | `DATE` | — |
| `status` | `STRING` | — |
| `valid_from` | `TIMESTAMP` | — |
| `valid_to` | `TIMESTAMP` | — |
| `is_current` | `BOOL` | — |

---

# Gold Models and Analytics Marts

## `customer_cohorts`

**Model type:** Analytics Mart

**Grain:** one row per cohort month × activity month

**Purpose:** Customer retention mart based on first completed purchase month and monthly activity.

| Column | Warehouse Type | Description |
|---|---|---|
| `cohort_month_key` | `STRING` | — |
| `cohort_month` | `DATE` | — |
| `activity_month` | `DATE` | — |
| `month_number` | `INT64` | — |
| `cohort_size` | `INT64` | — |
| `active_customers` | `INT64` | — |
| `transaction_count` | `INT64` | — |
| `total_sales` | `NUMERIC` | — |
| `retention_rate` | `FLOAT64` | — |
| `sales_per_active_customer` | `NUMERIC` | — |

---

## `customer_rfm`

**Model type:** Analytics Mart

**Grain:** one row per purchasing customer

**Purpose:** Customer-level Recency, Frequency, and Monetary mart used for segmentation.

| Column | Warehouse Type | Description |
|---|---|---|
| `customer_id` | `INT64` | — |
| `customer_sk` | `STRING` | — |
| `full_name` | `STRING` | — |
| `city` | `STRING` | — |
| `loyalty_tier` | `STRING` | — |
| `signup_date` | `DATE` | — |
| `as_of_date` | `DATE` | — |
| `first_purchase_date` | `DATE` | — |
| `last_purchase_date` | `DATE` | — |
| `recency_days` | `INT64` | — |
| `frequency` | `INT64` | — |
| `monetary` | `NUMERIC` | — |
| `average_order_value` | `NUMERIC` | — |
| `recency_score` | `INT64` | — |
| `frequency_score` | `INT64` | — |
| `monetary_score` | `INT64` | — |
| `rfm_score` | `STRING` | — |
| `rfm_total_score` | `INT64` | — |
| `customer_segment` | `STRING` | — |

---

## `executive_daily`

**Model type:** Analytics Mart

**Grain:** one row per business date

**Purpose:** Executive-level daily KPI mart used by the Executive Overview dashboard.

| Column | Warehouse Type | Description |
|---|---|---|
| `date_key` | `INT64` | — |
| `business_date` | `DATE` | — |
| `year` | `INT64` | — |
| `quarter` | `INT64` | — |
| `month_number` | `INT64` | — |
| `month_name` | `STRING` | — |
| `iso_year` | `INT64` | — |
| `iso_week` | `INT64` | — |
| `day_of_month` | `INT64` | — |
| `day_of_week_number` | `INT64` | — |
| `day_name` | `STRING` | — |
| `is_weekend` | `BOOL` | — |
| `active_stores` | `INT64` | — |
| `store_days` | `INT64` | — |
| `transaction_count` | `INT64` | — |
| `product_quantity` | `INT64` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_sales` | `NUMERIC` | — |
| `item_sales` | `NUMERIC` | — |
| `total_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |
| `aov` | `NUMERIC` | — |
| `ads` | `NUMERIC` | — |
| `adq` | `FLOAT64` | — |
| `gross_margin_rate` | `NUMERIC` | — |

---

## `product_performance`

**Model type:** Analytics Mart

**Grain:** one row per historical product version × business date

**Purpose:** Product-level daily mart for sales, quantity, category, cost, and margin analysis.

| Column | Warehouse Type | Description |
|---|---|---|
| `product_day_key` | `STRING` | — |
| `date_key` | `INT64` | — |
| `business_date` | `DATE` | — |
| `year` | `INT64` | — |
| `quarter` | `INT64` | — |
| `month_number` | `INT64` | — |
| `month_name` | `STRING` | — |
| `iso_year` | `INT64` | — |
| `iso_week` | `INT64` | — |
| `day_name` | `STRING` | — |
| `is_weekend` | `BOOL` | — |
| `product_sk` | `STRING` | — |
| `product_id` | `INT64` | — |
| `sku` | `STRING` | — |
| `product_name` | `STRING` | — |
| `size` | `STRING` | — |
| `category_id` | `INT64` | — |
| `category_name` | `STRING` | — |
| `category_group` | `STRING` | — |
| `base_price` | `NUMERIC` | — |
| `unit_cost` | `NUMERIC` | — |
| `transaction_count` | `INT64` | — |
| `order_line_count` | `INT64` | — |
| `product_quantity` | `INT64` | — |
| `discount_amount` | `NUMERIC` | — |
| `product_sales` | `NUMERIC` | — |
| `total_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |
| `average_selling_price` | `NUMERIC` | — |
| `avg_units_per_transaction` | `FLOAT64` | — |
| `gross_margin_rate` | `NUMERIC` | — |

---

## `store_performance`

**Model type:** Analytics Mart

**Grain:** one row per store × business date

**Purpose:** Store-level daily performance mart for region, area, store type, and store analysis.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_day_key` | `STRING` | — |
| `date_key` | `INT64` | — |
| `business_date` | `DATE` | — |
| `year` | `INT64` | — |
| `quarter` | `INT64` | — |
| `month_number` | `INT64` | — |
| `month_name` | `STRING` | — |
| `iso_year` | `INT64` | — |
| `iso_week` | `INT64` | — |
| `day_name` | `STRING` | — |
| `is_weekend` | `BOOL` | — |
| `store_sk` | `STRING` | — |
| `store_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `area_id` | `INT64` | — |
| `area_name` | `STRING` | — |
| `region_id` | `INT64` | — |
| `region_name` | `STRING` | — |
| `transaction_count` | `INT64` | — |
| `product_quantity` | `INT64` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_sales` | `NUMERIC` | — |
| `item_sales` | `NUMERIC` | — |
| `total_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |
| `aov` | `NUMERIC` | — |
| `daily_sales` | `NUMERIC` | — |
| `daily_quantity` | `INT64` | — |
| `gross_margin_rate` | `NUMERIC` | — |
| `is_open_day` | `BOOL` | — |

---

## `dim_customer`

**Model type:** Dimension

**Grain:** one row per customer

**Purpose:** SCD Type 1 customer dimension representing the latest known customer state.

| Column | Warehouse Type | Description |
|---|---|---|
| `customer_sk` | `STRING` | — |
| `customer_id` | `INT64` | — |
| `full_name` | `STRING` | — |
| `email` | `STRING` | — |
| `phone` | `STRING` | — |
| `birth_date` | `DATE` | — |
| `gender` | `STRING` | — |
| `city` | `STRING` | — |
| `signup_date` | `DATE` | — |
| `signup_store_id` | `INT64` | — |
| `loyalty_tier` | `STRING` | — |
| `updated_at` | `TIMESTAMP` | — |

---

## `dim_date`

**Model type:** Dimension

**Grain:** one row per calendar date

**Purpose:** Calendar dimension for date-based reporting.

| Column | Warehouse Type | Description |
|---|---|---|
| `date_key` | `INT64` | — |
| `calendar_date` | `DATE` | — |
| `year` | `INT64` | — |
| `quarter` | `INT64` | — |
| `month_number` | `INT64` | — |
| `month_name` | `STRING` | — |
| `iso_year` | `INT64` | — |
| `iso_week` | `INT64` | — |
| `day_of_month` | `INT64` | — |
| `day_of_week_number` | `INT64` | — |
| `day_name` | `STRING` | — |
| `week_start_date` | `DATE` | — |
| `month_start_date` | `DATE` | — |
| `quarter_start_date` | `DATE` | — |
| `year_start_date` | `DATE` | — |
| `is_weekend` | `BOOL` | — |

---

## `dim_product`

**Model type:** Dimension

**Grain:** one row per historical product version

**Purpose:** SCD Type 2 product dimension for historical product and cost resolution.

| Column | Warehouse Type | Description |
|---|---|---|
| `product_sk` | `STRING` | — |
| `product_id` | `INT64` | — |
| `category_id` | `INT64` | — |
| `category_name` | `STRING` | — |
| `category_group` | `STRING` | — |
| `sku` | `STRING` | — |
| `product_name` | `STRING` | — |
| `size` | `STRING` | — |
| `base_price` | `NUMERIC` | — |
| `unit_cost` | `NUMERIC` | — |
| `is_active` | `BOOL` | — |
| `launched_date` | `DATE` | — |
| `valid_from` | `TIMESTAMP` | — |
| `valid_to` | `TIMESTAMP` | — |
| `is_current` | `BOOL` | — |

---

## `dim_promotion`

**Model type:** Dimension

**Grain:** one row per promotion

**Purpose:** Promotion dimension.

| Column | Warehouse Type | Description |
|---|---|---|
| `promotion_sk` | `STRING` | — |
| `promotion_id` | `INT64` | — |
| `promo_code` | `STRING` | — |
| `promo_name` | `STRING` | — |
| `promo_type` | `STRING` | — |
| `discount_value` | `NUMERIC` | — |
| `min_order_amount` | `NUMERIC` | — |
| `start_date` | `DATE` | — |
| `end_date` | `DATE` | — |
| `updated_at` | `TIMESTAMP` | — |

---

## `dim_store`

**Model type:** Dimension

**Grain:** one row per historical store version

**Purpose:** SCD Type 2 store dimension for historical store hierarchy resolution.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_sk` | `STRING` | — |
| `store_id` | `INT64` | — |
| `area_id` | `INT64` | — |
| `region_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `latitude` | `NUMERIC` | — |
| `longitude` | `NUMERIC` | — |
| `opened_date` | `DATE` | — |
| `closed_date` | `DATE` | — |
| `status` | `STRING` | — |
| `area_name` | `STRING` | — |
| `region_name` | `STRING` | — |
| `valid_from` | `TIMESTAMP` | — |
| `valid_to` | `TIMESTAMP` | — |
| `is_current` | `BOOL` | — |

---

## `dim_time`

**Model type:** Dimension

**Grain:** one row per minute of day

**Purpose:** Minute-level time dimension for time-of-day analysis.

| Column | Warehouse Type | Description |
|---|---|---|
| `time_key` | `INT64` | — |
| `hour_24` | `INT64` | — |
| `minute` | `INT64` | — |
| `time_value` | `TIME` | — |
| `time_label` | `STRING` | — |
| `daypart` | `STRING` | — |

---

## `fct_order_items`

**Model type:** Fact

**Grain:** one row per latest order item

**Purpose:** Latest-state order-item fact with historical product cost and gross margin.

| Column | Warehouse Type | Description |
|---|---|---|
| `order_item_id` | `INT64` | — |
| `order_id` | `INT64` | — |
| `business_date` | `DATE` | — |
| `order_ts` | `TIMESTAMP` | — |
| `store_id` | `INT64` | — |
| `store_sk` | `STRING` | — |
| `customer_id` | `INT64` | — |
| `promotion_id` | `INT64` | — |
| `order_status` | `STRING` | — |
| `order_channel` | `STRING` | — |
| `product_id` | `INT64` | — |
| `product_sk` | `STRING` | — |
| `quantity` | `INT64` | — |
| `unit_price` | `NUMERIC` | — |
| `line_discount` | `NUMERIC` | — |
| `line_total` | `NUMERIC` | — |
| `historical_unit_cost` | `NUMERIC` | — |
| `line_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |
| `updated_at` | `TIMESTAMP` | — |

---

## `fct_orders`

**Model type:** Fact

**Grain:** one row per latest order

**Purpose:** Latest-state order fact used for realized sales and transaction analysis.

| Column | Warehouse Type | Description |
|---|---|---|
| `order_id` | `INT64` | — |
| `order_number` | `STRING` | — |
| `store_id` | `INT64` | — |
| `store_sk` | `STRING` | — |
| `customer_id` | `INT64` | — |
| `promotion_id` | `INT64` | — |
| `order_ts` | `TIMESTAMP` | — |
| `business_date` | `DATE` | — |
| `order_channel` | `STRING` | — |
| `order_status` | `STRING` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_amount` | `NUMERIC` | — |
| `updated_at` | `TIMESTAMP` | — |

---

## `fct_payments`

**Model type:** Fact

**Grain:** one row per latest payment

**Purpose:** Latest-state payment fact kept separate from order sales lifecycle logic.

| Column | Warehouse Type | Description |
|---|---|---|
| `payment_id` | `INT64` | — |
| `order_id` | `INT64` | — |
| `business_date` | `DATE` | — |
| `order_ts` | `TIMESTAMP` | — |
| `store_id` | `INT64` | — |
| `store_sk` | `STRING` | — |
| `customer_id` | `INT64` | — |
| `payment_method` | `STRING` | — |
| `amount` | `NUMERIC` | — |
| `payment_status` | `STRING` | — |
| `paid_at` | `TIMESTAMP` | — |
| `updated_at` | `TIMESTAMP` | — |

---

## `fct_store_daily_sales`

**Model type:** Fact

**Grain:** one row per store × business date

**Purpose:** Authoritative denominator-complete store-day KPI fact used for ADS and ADQ.

| Column | Warehouse Type | Description |
|---|---|---|
| `store_day_key` | `STRING` | — |
| `business_date` | `DATE` | — |
| `store_sk` | `STRING` | — |
| `store_id` | `INT64` | — |
| `area_id` | `INT64` | — |
| `store_code` | `STRING` | — |
| `store_name` | `STRING` | — |
| `store_type` | `STRING` | — |
| `city` | `STRING` | — |
| `transaction_count` | `INT64` | — |
| `subtotal` | `NUMERIC` | — |
| `discount_amount` | `NUMERIC` | — |
| `tax_amount` | `NUMERIC` | — |
| `total_sales` | `NUMERIC` | — |
| `product_quantity` | `INT64` | — |
| `item_sales` | `NUMERIC` | — |
| `total_cost` | `NUMERIC` | — |
| `gross_margin` | `NUMERIC` | — |
| `aov` | `NUMERIC` | — |
| `is_open_day` | `BOOL` | — |

---

# Business-Facing Mart Summary

| Mart | Grain | Primary Use |
|---|---|---|
| `executive_daily` | business date | Executive KPIs and daily trends |
| `store_performance` | store × business date | Region, area, store-type, and store performance |
| `product_performance` | historical product version × business date | Product and category performance |
| `customer_cohorts` | cohort month × activity month | Customer retention and cohort analysis |
| `customer_rfm` | purchasing customer | Customer behavior and RFM segmentation |

# BI Usage

- Executive Overview → `executive_daily`
- Store Performance → `store_performance`
- Product Performance → `product_performance`
- Customer Retention → `customer_cohorts`
- Customer RFM → `customer_rfm`

# Notes

Column data types come from the BigQuery catalog generated by dbt. Column descriptions come from dbt YAML metadata where available.

For business definitions of ADS, ADQ, AOV, Gross Margin, cohort retention, and RFM metrics, see `docs/kpi_definitions.md`.
