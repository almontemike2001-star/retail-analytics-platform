select
    store_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_stores') }}
group by store_id, updated_at
having count(*) > 1
