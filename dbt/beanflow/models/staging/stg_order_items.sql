with source as (

    select *
    from {{ source('raw_pos', 'order_items') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by order_item_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    line_discount,
    line_total,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
