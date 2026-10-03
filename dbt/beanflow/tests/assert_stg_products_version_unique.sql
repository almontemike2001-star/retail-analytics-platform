select
    product_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_products') }}
group by product_id, updated_at
having count(*) > 1
