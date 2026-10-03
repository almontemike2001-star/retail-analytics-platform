select
    order_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_orders') }}
group by order_id, updated_at
having count(*) > 1
