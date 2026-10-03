select
    store_day_key,
    transaction_count,
    total_sales,
    product_quantity
from {{ ref('fct_store_daily_sales') }}
where transaction_count < 0
   or total_sales < 0
   or product_quantity < 0
