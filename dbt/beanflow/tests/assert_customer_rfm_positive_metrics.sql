select
    customer_id,
    frequency,
    monetary,
    average_order_value

from {{ ref('customer_rfm') }}

where frequency <= 0
   or monetary <= 0
   or average_order_value <= 0
