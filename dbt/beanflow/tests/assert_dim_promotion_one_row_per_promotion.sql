select
    promotion_id,
    count(*) as row_count
from {{ ref('dim_promotion') }}
group by promotion_id
having count(*) != 1
