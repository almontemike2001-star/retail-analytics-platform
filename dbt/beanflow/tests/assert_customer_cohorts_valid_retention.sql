select
    cohort_month,
    activity_month,
    month_number,
    cohort_size,
    active_customers,
    retention_rate

from {{ ref('customer_cohorts') }}

where retention_rate < 0
   or retention_rate > 1
   or active_customers > cohort_size
