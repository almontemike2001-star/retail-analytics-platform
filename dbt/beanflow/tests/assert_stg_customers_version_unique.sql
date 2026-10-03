select
    customer_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_customers') }}
group by customer_id, updated_at
having count(*) > 1
