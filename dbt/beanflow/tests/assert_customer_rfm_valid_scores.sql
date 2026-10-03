select
    customer_id,
    recency_score,
    frequency_score,
    monetary_score,
    rfm_total_score

from {{ ref('customer_rfm') }}

where recency_score not between 1 and 5
   or frequency_score not between 1 and 5
   or monetary_score not between 1 and 5
   or rfm_total_score not between 3 and 15
