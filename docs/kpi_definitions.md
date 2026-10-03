# BeanFlow Coffee — KPI Definitions

## Overview

This document defines the core business metrics used across the BeanFlow Coffee analytics platform.

The goal is to keep KPI logic consistent across:

- dbt models
- analytics marts
- Metabase dashboards
- ad-hoc analysis
- portfolio documentation

All metrics are based on synthetic data.

---

## 1. Realized Sales

### Definition

Realized Sales represents revenue from completed orders only.

### Business Rule

Included:

- `order_status = 'completed'`

Excluded:

- cancelled orders
- refunded orders

### Formula

```text
Realized Sales = SUM(total)
WHERE order_status = 'completed'
```

### Source

Primary source:

```text
fct_orders
```

### Notes

Order status is the authoritative source for realized sales.

Payment status is not used as the primary sales definition because order lifecycle and payment lifecycle represent different business processes.

---

## 2. Transactions

### Definition

Transactions represent the number of completed orders.

### Formula

```text
Transactions = COUNT(completed orders)
```

or, at an aggregated mart level:

```text
SUM(transaction_count)
```

### Sources

```text
fct_orders
fct_store_daily_sales
executive_daily
store_performance
```

Cancelled and refunded orders are excluded from realized transaction counts.

---

## 3. Product Quantity

### Definition

Product Quantity represents the total number of product units sold through completed orders.

### Formula

```text
Product Quantity = SUM(quantity)
```

for order items associated with completed orders.

### Sources

```text
fct_order_items
fct_store_daily_sales
```

---

## 4. Average Order Value — AOV


### Definition

Average Order Value represents the average sales value generated per completed transaction.

### Formula

```text
AOV = Total Sales / Transactions
```

At aggregated levels:

```text
SUM(total_sales) / SUM(transaction_count)
```

### Aggregation Rule

Do not average already-calculated AOR values.

Incorrect:

```text
AVG(daily_aov)
```

Correct:

```text
SUM(total_sales) / SUM(transaction_count)
```

### Validated Example

```text
Total Sales = 5,205,346.11
Transactions = 17,341
AOV ≈ 300.18
```

### Typical Sources

```text
executive_daily
store_performance
```

---

## 5. Store-Day

### Definition

 A Store-Day represents one eligible operating store on one business date.

The unique identifier is:

```text
store_day_key
```

### Grain

```text
store × business date
```

### Purpose

Store-Day is the denominator used for ADS and ADQ.

The model intentionally preserves eligible open stores even when a store records zero completed sales. This prevents ADS and ADQ from being overstated.

### Source

```text
fct_store_daily_sales
```

---

## 6. Average Daily Sales — ADS

### Definition

Average Daily Sales measures sales generated per eligible open store-day.

### Formula

```text
ADS = Total Sales / Open Store-Days
```

At an aggregated level:

```text
SUM(total_sales) / COUNT(DISTINCT store_day_key)
```

### Filter Behavior

ADS can be filtered dynamically by:

- region
- area
- store
- store type
- business date

The formula remains unchanged because the distinct Store-Day denominator responds to filter context.

### Validated Example

```text
Total Sales = 5,205,346.11
Store-Days = 805
ADS ≈ 6,466.27
```

### Authoritative Source

```text
fct_store_daily_sales
```

Typical mart:

```text
store_performance
```

---

## 7. Average Daily Quantity — ADQ

### Definition

Average Daily Quantity measures product units sold per eligible open store-day.

### Formula

```text
ADQ = Product Quantity / Open Store-Days
```

At an aggregated level:

```text
SUM(product_quantity) / COUNT(DISTINCT store_day_key)
```

### Aggregation Rule

Incorrect:

```text
AVG(daily_adq)
```

Correct:

```text
SUM(product_quantity) / COUNT(DISTINCT store_day_key)
```

### Validated Example

```text
Product Quantity = 30,751
Store-Days = 805
ADQ >. 38.20
```

### Authoritative Source

```text
fct_store_daily_sales
```

---

## 8. Item Sales

### Definition

Item Sales represents product-level sales before tax and is used as the revenue basis for product gross margin calculations.

### Source

```text
fct_order_items
```

### Notes

Product-level Item Sales can differ from order-level Total Sales because order totals include tax while Item Sales is used as the product margin basis.

---

## 9. Product Cost

### Definition

Product Cost represents the historical cost applicable when the transaction occurred.

### Formula

```text
Product Cost = Quantity × Historical Unit Cost
```

### Historical Resolution

Historical unit cost is resolved through point-in-time joins to the SCD Type 2 product dimension.

```text
valid_from <= transaction_timestamp
AND transaction_timestamp < valid_to
```

### Sources

```text
dim_product
fct_order_items
```

---

## 10. Gross Margin

### Definition

Gross Margin represents product-level sales remaining after historical product cost.

### Formula

```text
Gross Margin = Item Sales - Product Cost
```

### Validated Example

```text
Item Sales = 4,680,064.00
Product Cost = 1,610,925.36
Gross Margin = 3,069,138.64
```

### Sources

```text
fct_order_items
product_performance
executive_daily
store_performance
```

---

## 11. Gross Margin %

### Definition

Gross Margin Percentage measures the proportion of Item Sales remaining after product cost.

### Formula

```text
Gross Margin % = Gross Margin / Item Sales
```

At an aggregated level:

```text
SUM(gross_margin) / SUM(item_sales)
```

### Aggregation Rule

Incorrect:

```text
AVG(gross_margin_pct)
```

Correct:

```text
SUM(gross_margin) / SUM(item_sales)
```

### Validated Example

```text
Gross Margin = 3,069,138.64
Item Sales = 4,680,064.00
Gross Margin % ≈ 65.58%
```

---

## 12. Product Sales

### Definition

Product Sales represents sales attributed to individual product lines.

### Formula

```text
Product Sales = SUM(item_sales)
```

## Source

```text
product_performance
```

### Notes

Product Sales should not be expected to equal order-level Total Sales because Product Sales is based on item-level sales while order totals include tax.

---

## 13. Units Sold

### Definition

Units Sold represents total product quantity sold.

### Formula

```text
Units Sold = SUM(product_quantity)
```

### Source

```text
product_performance
```

---

## 14. Average Selling Price

### Definition

Average Selling Price represents average item-level sales per unit sold.

### Formula

```text
Average Selling Price =
SUM(product_sales) / SUM(product_quantity)
```

Do not average lower-grain selling-price averages.

---

## 15. Customer Cohort

### Definition

A Customer Cohort groups customers based on the month of their first completed purchase.

### Formula

```text
cohort_month = MONTH(first completed purchase date)
```

### Source

```text
customer_cohorts
```

---

## 16. Cohort Size

### Definition

Cohort Size represents the number of customers whose first completed purchase occurred in a specific cohort month.

For a cohort:

```text
Month Number = 0
```

represents the original cohort population.

### Source

```text
customer_cohorts
```

---

## 17. Active Customers

### Definition

Active Customers represents customers from a cohort who completed at least one purchase in a given activity month.

### Grain

```text
cohort_month × activity_month
```

### Source

```text
customer_cohorts
```

---

## 18. Cohort Month Number

### Definition

Month Number measures how far an activity month is from the original cohort month.

```text
Month 0 = acquisition month
Month 1 = one month after acquisition
Month 2 = two months after acquisition
```

### Source

```text
customer_cohorts
```

---

## 19. Retention Rate

### Definition

Retention Rate measures the percentage of the original cohort that is active in a given activity month.

### Formula

```text
Retention Rate = Active Customers / Original Cohort Size
```

### Interpretation

For example:

```text
Month 0 = 100%
Month 1 = 9.44%
```

means 9.44% of the original cohort returned and purchased during the following cohort month.

### Retention Type

The model uses:

```text
non-cumulative monthly retention
```

A customer is counted as active only if they purchased during that specific activity month.

### Current Project Limitation

The current synthetic analytical history is short, so the retention mart is intended primarily to demonstrate cohort modeling, retention calculation, and BI visualization rather than long-term customer behavior.

---

## 20. RFM Analysis

RFM stands for:

```text
Recency
Frequency
Monetary
```

The RFM mart contains one row per purchasing customer.

### Source

```text
customer_rfm
```

---

## 21. Recency

### Definition

Recency represents the number of days since a customer most recently completed a purchase relative to the RFM analysis date.

Lower values indicate more recent activity.

```text
Recency = 0
```

means the customer purchased on the analysis date.

---

## 22. Frequency

### Definition

Frequency represents the number of completed transactions associated with a customer during the analysis period.

### Formula

```text
Frequency = Count of completed customer transactions
```

Higher frequency indicates more repeated purchasing activity.

---

## 23. Monetary Value

### Definition

Monetary Value represents total completed-order sales associated with a customer.

### Formula

```text
Monetary = SUM(completed customer sales)
```

### Notes

RFM includes identified purchasing customers only. Anonymous or guest purchases that cannot be associated with a customer are not represented in customer-level Monetary values.

---

## 24. Purchasing Customers

### Definition

Purchasing Customers represents the number of customers present in the RFM mart.

Because `customer_rfm` has one row per purchasing customer:

```text
Purchasing Customers = COUNT(rows)
```

### Validated Value

```text
7,332
```

for the current synthetic analytical period.

---

## 25. Customer Sales

### Definition

Customer Sales represents total completed sales attributable to identified purchasing customers.

### Formula

```text
Customer Sales = SUM((monetary))
```

### Validated Value

```text
3,285,437.86
```

### Important Difference

Customer Sales can be lower than company Total Sales because not every completed order is necessarily associated with an identified customer.

---

## 26. Average Customer Spend

### Definition

Average Customer Spend represents average total Monetary value per purchasing customer during the analysis period.

### Formula

```text
Average Customer Spend = AVG(monetary)
```

Because the RFM mart contains one row per purchasing customer, this represents average customer-level spend.

---

## 27. RFM Customer Segment

### Definition

Customer Segment classifies purchasing customers based on RFM behavior.

Current segment labels include:

- Champions
- Loyal Customers
- Potential Loyalists
- Needs Attention
- At Risk
- Hibernating
- New Customers

### Purpose

Segments provide a business-friendly view of customer behavior for:

- customer targeting
- retention analysis
- customer value analysis
- dashboard segmentation

### Current Project Limitation

Because the current dataset covers a short analytical history, these segment assignments are primarily a demonstration of the RFM pipeline rather than production customer-lifecycle classifications.

---

## 28. Business Date

### Definition

Business Date represents the retail operating date associated with a transaction.

It is used for:

- daily aggregation
- dashboard date filters
- store-day construction
- sales trends
- cohort analysis where applicable

---

## 29. Eligible Open Store

### Definition

An Eligible Open Store is a store considered operational for a given business date.

Stores with opening dates after the analyzed date are excluded from the Store-Day denominator.

### Purpose

This prevents future stores from incorrectly lowering ADS and ADQ.

---

## 30. KPI Aggregation Principles

### Additive Measures

These can generally be summed:

```text
Total Sales
Transaction Count
Product Quantity
Item Sales
Product Cost
Gross Margin
```

### Non-Additive or Ratio Measures

These must be recalculated:

```text
AOV
ADS
ADQ
Gross Margin %
Retention Rate
Average Selling Price
```

### General Rule

Do not average pre-calculated ratios when reporting at a higher grain.

Instead, aggregate the numerator and denominator and then calculate the ratio where the business definition supports it.

---

## 31. Dashboard Metric Mapping

### Executive Overview

Primary mart:

```text
executive_daily
```

Metrics:

- Total Sales
- Transactions
- AOV
- ADS
- ADQ
- Gross Margin
- Gross Margin %
- daily sales trends

### Store Performance

Primary mart:

```text
store_performance
```

Metrics:

- Total Sales
- Transactions
- ADS
- ADQ
- AOV
- Gross Margin
- Gross Margin %
- regional and store rankings

### Product Performance

Primary mart:

```text
product_performance
```

Metrics:

- Product Sales
- Units Sold
- Gross Margin
- Gross Margin %
- Average Selling Price

### Customer Retention

Primary mart:

```text
customer_cohorts
```

Metrics:

- Cohort Size
- Active Customers
- Month Number
- Retention Rate

### Customer RFM

Primary mart:

```text
customer_rfm
```

Metrics:

- Purchasing Customers
- Customer Sales
- Average Customer Spend
- Recency
- Frequency
- Monetary
- Customer Segment

---

## Summary

BeanFlow Coffee uses explicit KPI definitions so business metrics remain consistent across transformation and BI layers.

The most important modeling rules are:

1. completed orders define realized sales
2. Store-Day is the denominator for ADS and ADQ
3. zero-sales eligible store-days are preserved
4. historical product cost is resolved through SCD Type 2
5. ratios are recalculated from their components
6. cohort retention is non-cumulative monthly retention
7. RFM operates at one row per identified purchasing customer

These rules help ensure dashboard metrics remain explainable, reproducible, and consistent across filtering and aggregation levels.
