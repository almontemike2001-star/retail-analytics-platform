with source as (

    select *
    from {{ source('raw_pos', 'customers') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by customer_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    customer_id,
    full_name,
    email,
    phone,
    birth_date,
    gender,
    city,
    signup_date,
    signup_store_id,
    loyalty_tier,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
