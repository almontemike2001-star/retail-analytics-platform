select
    to_hex(md5(
        concat(
            cast(s.store_id as string),
            '|',
            cast(s.valid_from as string)
        )
    )) as store_sk,

    s.store_id,
    s.area_id,
    a.region_id,

    s.store_code,
    s.store_name,
    s.store_type,
    s.city,
    s.latitude,
    s.longitude,
    s.opened_date,
    s.closed_date,
    s.status,

    a.area_name,
    r.region_name,

    s.valid_from,
    s.valid_to,
    s.is_current

from {{ ref('int_store_versions') }} s

left join {{ ref('stg_areas') }} a
    on s.area_id = a.area_id

left join {{ ref('stg_regions') }} r
    on a.region_id = r.region_id
