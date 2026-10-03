select
    cohort_month,
    cohort_size,
    active_customers,
    retention_rate

from {{ ref('customer_cohorts') }}

where month_number = 0
  and (
      active_customers != cohort_size
      or retention_rate != 1
  )
