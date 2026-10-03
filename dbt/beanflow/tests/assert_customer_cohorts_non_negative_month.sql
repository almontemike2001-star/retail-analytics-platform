select
    cohort_month,
    activity_month,
    month_number

from {{ ref('customer_cohorts') }}

where month_number < 0
