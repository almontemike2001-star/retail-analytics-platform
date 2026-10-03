# BeanFlow Coffee — Business Insights

## Overview

This document summarizes the key business findings produced by the BeanFlow Coffee analytics platform.

All observations are based on synthetic retail data generated for the portfolio project.

The current analytical window covers seven business days from:

```text
2026-09-25
to
2026-10-01
```

Because the period is intentionally short, customer retention and RFM findings should be interpreted as demonstrations of analytical capability rather than long-term behavioral conclusions.

---

## 1. Executive Performance

Across the seven-day analytical period:

```text
Total Sales: 5,205,346.11
Transactions: 17,341
Product Quantity: 30,751
Store-Days: 805
```

Derived company-level KPIs:

```text
AOV: 300.18
ADS: 6,466.27
ADQ: 38.20
```

Gross margin performance:

```text
Item Sales: 4,680,064.00
Product Cost: 1,610,925.36
Gross Margin: 3,069,138.64
Gross Margin %: 65.58%
```

These metrics reconcile across the Gold facts and business-facing marts.

---

## 2. Daily Sales Trend

| Business Date | Sales | Transactions | Product Qty | AOV | ADS | ADQ | Gross Margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-25 | 727,312.32 | 2,494 | 4,299 | 291.62 | 6,324.45 | 37.38 | 429,411.23 |
| 2026-09-26 | 821,418.08 | 2,617 | 4,785 | 313.88 | 7,142.77 | 41.61 | 480,523.36 |
| 2026-09-27 | 734,005.44 | 2,400 | 4,275 | 305.84 | 6,382.66 | 37.17 | 430,460.41 |
| 2026-09-28 | 698,090.40 | 2,309 | 4,111 | 302.33 | 6,070.35 | 35.75 | 408,217.05 |
| 2026-09-29 | 684,010.85 | 2,349 | 4,095 | 291.19 | 5,947.92 | 35.61 | 407,172.60 |
| 2026-09-30 | 790,964.94 | 2,648 | 4,710 | 298.70 | 6,877.96 | 40.96 | 468,772.26 |
| 2026-10-01 | 749,544.08 | 2,524 | 4,476 | 296.97 | 6,517.77 | 38.92 | 444,581.73 |

### Key observations

- The strongest sales day was **2026-09-26**, with approximately **821.4K** in sales.
- The lowest sales day was **2026-09-29**, with approximately **684.0K**.
- ADS was highest on **2026-09-26** at approximately **7,142.77**.
- ADQ also peaked on **2026-09-26** at approximately **41.61**.
- AOV remained relatively stable around the 290–314 range.
- Gross Margin % remained consistently near 65–66%, indicating stable product cost structure across the short period.

---

## 3. Regional Performance

| Region | Sales | Store-Days | ADS | ADQ |
|---|---:|---:|---:|---:|
| Metro Manila | 2,448,210.11 | 350 | 6,994.89 | 41.47 |
| North Luzon | 631,182.38 | 112 | 5,635.56 | 32.80 |
| South Luzon | 1,225,068.41 | 203 | 6,034.82 | 36.00 |
| Visayas & Mindanao | 900,885.21 | 140 | 6,434.89 | 37.53 |

### Key observations

- **Metro Manila** generated the highest absolute sales and the highest ADS.
- Metro Manila also had the highest ADQ.
- **North Luzon** had the lowest ADS and ADQ among the four regions.
- South Luzon generated more total sales than Visayas & Mindanao because it contributed more Store-Days.
- Visayas & Mindanao produced a higher ADS than South Luzon despite having fewer Store-Days.

This shows why both absolute sales and normalized KPIs such as ADS and ADQ are necessary for regional comparison.

---

## 4. Store-Day Coverage

The denominator-complete store-day model generated:

```text
805 Store-Days
```

This corresponds to:

```text
115 eligible stores × 7 business days
```

Two stores were excluded because their opening dates occurred after the current analytical period:

```text
BeanFlow Dasmariñas Kiosk
BeanFlow Davao City Drive-Thru
```

Although the current seven-day sample contains no zero-sales eligible Store-Days, the model intentionally preserves them when they occur.

This design prevents ADS and ADQ from being overstated in future data.

---

## 5. Product Performance

Across completed transactions:

```text
Product Quantity: 30,751
Product Sales: 4,680,064.00
Product Cost: 1,610,925.36
Gross Margin: 3,069,138.64
Gross Margin %: 65.58%
```

### Key observations

- Product-level sales are lower than order-level Total Sales because product sales are measured before tax while order totals include tax.
- Gross Margin % remains consistent with the executive and store-level reporting.
- Historical product cost is resolved through SCD Type 2 product history rather than using only the current product cost.
- Ten products received historical price changes during the test period, demonstrating that the platform can preserve historical product versions.

---

## 6. Order and Payment Status

Observed order statuses:

| Status | Orders | Amount |
|---|---:|---:|
| Completed | 17,341 | 5,205,346.11 |
| Cancelled | 330 | 101,813.04 |
| Refunded | 102 | 30,947.84 |

Observed payment statuses:

| Status | Payments | Amount |
|---|---:|---:|
| Paid | 17,640 | 5,236,293.95 |
| Failed | 197 | 58,822.96 |
| Refunded | 102 | 30,947.84 |

### Key observation

Order status and payment status should not be treated as interchangeable.

Realized sales are based on completed orders rather than paid payment records.

---

## 7. Customer Cohort Analysis

| Cohort | Month Number | Active Customers | Transactions | Sales | Retention |
|---|---:|---:|---:|---:|---:|
| Sep 2026 | 0 | 6,494 | 9,223 | 2,806,934.45 | 100.00% |
| Sep 2026 | 1 | 613 | 714 | 218,255.18 | 9.44% |
| Oct 2026 | 0 | 838 | 880 | 260,248.23 | 100.00% |

### Key observations

- The September cohort contains **6,494** purchasing customers in Month 0.
- **613** of those customers purchased again in Month 1.
- This produces a Month 1 retention rate of approximately **9.44%**.
- The October cohort currently contains **838** Month 0 customers.

### Interpretation limitation

The analytical history spans only seven days and crosses one month boundary.

The cohort model primarily demonstrates first-purchase cohort assignment, month-number calculation, active-customer tracking, non-cumulative monthly retention, and cohort visualization.

---

## 8. Customer RFM Analysis

The current RFM mart contains:

```text
7,332 purchasing customers
```

Customer-attributed completed sales:

```text
3,285,437.86
```

Average customer-level AOV is approximately:

```text
302.27
```

| Segment | Customers | Avg Recency | Avg Frequency | Avg Monetary | Sales |
|---|---:|---:|---:|---:|---:|
| At Risk | 1,567 | 4.67 | 1.25 | 389.13 | 609,760.48 |
| Hibernating | 1,367 | 4.83 | 1.00 | 302.56 | 413,596.96 |
| Needs Attention | 1,146 | 2.14 | 1.00 | 295.15 | 338,237.75 |
| Champions | 1,082 | 0.46 | 3.21 | 1,034.12 | 1,118,915.38 |
| Loyal Customers | 1,000 | 1.63 | 1.70 | 454.13 | 454,132.44 |
| Potential Loyalists | 945 | 0.66 | 1.00 | 308.35 | 291,386.58 |
| New Customers | 225 | 0.00 | 1.00 | 264.04 | 59,408.27 |

### Key observations

- **Champions** are the highest-value segment by a large margin.
- Champions have the highest average purchase frequency and the highest average monetary value.
- Although At Risk contains the largest number of customers, Champions generate substantially more total sales.
- Hibernating customers represent a large population with low frequency and relatively high recency.
- Loyal Customers show stronger repeated purchasing behavior than Potential Loyalists and Needs Attention.
- New Customers represent recent single-purchase customers in the short analysis window.

### Interpretation limitation

Because RFM is calculated over only a short analytical period, the segments are primarily a pipeline demonstration.

---

## 9. Identified Customer Sales vs Company Sales

Company realized sales:

```text
5,205,346.11
```

Customer-attributed RFM sales:

```text
3,285,437.86
```

The difference exists because not every completed order is necessarily associated with an identified customer.

Customer-level metrics should not automatically be expected to reconcile to total company sales.

---

## 10. Data Quality Findings

The final dbt validation completed successfully:

```text
15 table models
15 view models
239 data tests

PASS=269
WARN=0
ERROR=0
SKIP=0
TOTAL=269
```

Additional validated behaviors include:

- Silver replay deduplication
- source-version preservation
- SCD Type 2 interval integrity
- point-in-time product joins
- store-day denominator construction
- order-sales reconciliation
- product-quantity reconciliation
- customer cohort calculations
- RFM grain validation

---

## 11. Business Interpretation

The short synthetic dataset demonstrates several useful analytical patterns:

1. Metro Manila leads both absolute and normalized performance.
2. North Luzon trails the other regions in both ADS and ADQ.
3. Daily sales vary meaningfully even when margin percentage remains relatively stable.
4. Store-Day normalization provides a fairer comparison across regions with different store counts.
5. Product margin analysis requires historically correct cost rather than current cost alone.
6. Customer retention requires a longer observation window before it becomes strategically meaningful.
7. RFM segmentation separates customer count from customer value: the largest segment is not necessarily the highest-value segment.
8. Customer-attributed sales and company sales answer different business questions and should remain distinct.

---

## 12. Recommended Future Analysis

With a longer synthetic or production history, the platform could support:

- 30-day and 90-day sales trends
- month-over-month performance
- year-over-year growth
- mature cohort retention curves
- customer lifetime value
- promotion effectiveness
- category contribution trends
- daypart performance
- weekday vs weekend behavior
- store opening ramp analysis
- churn-risk analysis
- regional benchmark comparisons
- basket composition analysis

The current architecture already provides the dimensional and fact-model foundation for these extensions.

---

## Summary

BeanFlow Coffee demonstrates more than dashboard creation.

The project connects:

```text
operational data
→ ingestion
→ historical transformation
→ dimensional modeling
→ KPI governance
→ business analysis
→ BI visualization
```

The resulting analytics layer provides consistent company, store, product, and customer perspectives while preserving clear metric definitions and historical correctness.
