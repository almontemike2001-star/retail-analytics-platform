select
    order_item_id,
    order_id,
    product_id,
    order_ts
from {{ ref('fct_order_items') }}
where product_sk is null
