with versions as (

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
        updated_at as valid_from,

        lead(updated_at) over (
            partition by product_id
            order by updated_at
        ) as valid_to

    from {{ ref('stg_products') }}

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
    valid_from,
    valid_to,
    valid_to is null as is_current
from versions
