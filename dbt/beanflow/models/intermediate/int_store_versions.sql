with versions as (

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
        updated_at as valid_from,

        lead(updated_at) over (
            partition by store_id
            order by updated_at
        ) as valid_to

    from {{ ref('stg_stores') }}

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
    valid_from,
    valid_to,
    valid_to is null as is_current
from versions
