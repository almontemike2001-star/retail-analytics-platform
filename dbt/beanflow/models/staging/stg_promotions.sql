with source as (

    select *
    from {{ source('raw_pos', 'promotions') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by promotion_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    promotion_id,
    promo_code,
    promo_name,
    promo_type,
    discount_value,
    min_order_amount,
    start_date,
    end_date,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
