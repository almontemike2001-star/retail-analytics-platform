with source as (

    select *
    from {{ source('raw_pos', 'payments') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by payment_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    payment_id,
    order_id,
    payment_method,
    amount,
    payment_status,
    paid_at,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
