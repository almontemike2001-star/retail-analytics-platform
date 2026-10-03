select
    store_id,
    countif(is_current) as current_versions
from {{ ref('dim_store') }}
group by store_id
having countif(is_current) != 1
