with source as (

    select *
    from {{ source('raw_pos', 'products') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by product_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    product_id,
    category_id,
    sku,
    product_name,
    size,
    base_price,
    unit_cost,
    is_active,
    launched_date,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
