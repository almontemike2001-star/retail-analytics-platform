select
    customer_id,
    as_of_date,
    last_purchase_date,
    recency_days

from {{ ref('customer_rfm') }}

where recency_days < 0
   or last_purchase_date > as_of_date
   or recency_days != date_diff(
       as_of_date,
       last_purchase_date,
       day
   )
