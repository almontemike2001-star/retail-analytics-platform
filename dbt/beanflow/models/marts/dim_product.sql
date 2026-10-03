select
    to_hex(md5(
        concat(
            cast(p.product_id as string),
            '|',
            cast(p.valid_from as string)
        )
    )) as product_sk,

    p.product_id,
    p.category_id,
    c.category_name,
    c.category_group,

    p.sku,
    p.product_name,
    p.size,
    p.base_price,
    p.unit_cost,
    p.is_active,
    p.launched_date,

    p.valid_from,
    p.valid_to,
    p.is_current

from {{ ref('int_product_versions') }} p

left join {{ ref('stg_product_categories') }} c
    on p.category_id = c.category_id
