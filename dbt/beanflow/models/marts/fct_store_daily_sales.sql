with store_calendar as (

    select *
    from {{ ref('int_store_calendar') }}

),

orders as (

    select *
    from {{ ref('int_store_daily_orders') }}

),

items as (

    select *
    from {{ ref('int_store_daily_items') }}

),

final as (

    select
        concat(
            cast(sc.store_id as string),
            '-',
            cast(sc.business_date as string)
        ) as store_day_key,

        sc.business_date,

        sc.store_sk,
        sc.store_id,
        sc.area_id,

        sc.store_code,
        sc.store_name,
        sc.store_type,
        sc.city,

        coalesce(o.transaction_count, 0) as transaction_count,

        coalesce(o.subtotal, 0) as subtotal,
        coalesce(o.discount_amount, 0) as discount_amount,
        coalesce(o.tax_amount, 0) as tax_amount,
        coalesce(o.total_sales, 0) as total_sales,

        coalesce(i.product_quantity, 0) as product_quantity,
        coalesce(i.item_sales, 0) as item_sales,
        coalesce(i.total_cost, 0) as total_cost,
        coalesce(i.gross_margin, 0) as gross_margin,

        safe_divide(
            coalesce(o.total_sales, 0),
            nullif(coalesce(o.transaction_count, 0), 0)
        ) as aov,

        true as is_open_day

    from store_calendar sc

    left join orders o
        on sc.store_id = o.store_id
       and sc.store_sk = o.store_sk
       and sc.business_date = o.business_date

    left join items i
        on sc.store_id = i.store_id
       and sc.store_sk = i.store_sk
       and sc.business_date = i.business_date

)

select *
from final
