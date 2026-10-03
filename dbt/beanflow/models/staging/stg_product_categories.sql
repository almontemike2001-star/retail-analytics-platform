select
    category_id,
    category_name,
    category_group
from {{ source('raw_pos', 'product_categories') }}
qualify row_number() over (
    partition by category_id
    order by _ingestion_date desc, _loaded_at desc
) = 1
