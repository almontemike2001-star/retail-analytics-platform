with source as (

    select *
    from {{ source('raw_pos', 'orders') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by order_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    order_id,
    order_number,
    store_id,
    customer_id,
    promotion_id,
    order_ts,
    order_channel,
    order_status,
    subtotal,
    discount_amount,
    tax_amount,
    total_amount,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
