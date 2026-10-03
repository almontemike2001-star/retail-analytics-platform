select
    i.order_item_id,
    i.order_id
from {{ ref('fct_order_items') }} i
left join {{ ref('fct_orders') }} o
    on i.order_id = o.order_id
where o.order_id is null
