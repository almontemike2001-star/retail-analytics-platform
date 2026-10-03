select
    area_id,
    region_id,
    area_name
from {{ source('raw_pos', 'areas') }}
qualify row_number() over (
    partition by area_id
    order by _ingestion_date desc, _loaded_at desc
) = 1
