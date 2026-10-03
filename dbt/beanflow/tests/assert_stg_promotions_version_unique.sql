select
    promotion_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_promotions') }}
group by promotion_id, updated_at
having count(*) > 1
