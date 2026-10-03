select
    region_id,
    region_name
from {{ source('raw_pos', 'regions') }}
qualify row_number() over (
    partition by region_id
    order by _ingestion_date desc, _loaded_at desc
) = 1
