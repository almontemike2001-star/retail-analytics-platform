select
    p.payment_id,
    p.order_id
from {{ ref('fct_payments') }} p
left join {{ ref('fct_orders') }} o
    on p.order_id = o.order_id
where o.order_id is null
