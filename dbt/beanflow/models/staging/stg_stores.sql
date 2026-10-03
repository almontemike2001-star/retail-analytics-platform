with source as (

    select *
    from {{ source('raw_pos', 'stores') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by store_id, updated_at
        order by
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    store_id,
    area_id,
    store_code,
    store_name,
    store_type,
    city,
    latitude,
    longitude,
    opened_date,
    closed_date,
    status,
    updated_at,

    _extract_batch_id,
    _extract_mode,
    _extracted_at,
    _source_file,
    _ingestion_date,
    _loaded_at
from deduplicated
