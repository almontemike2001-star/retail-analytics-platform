select
    order_item_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_order_items') }}
group by order_item_id, updated_at
having count(*) > 1
