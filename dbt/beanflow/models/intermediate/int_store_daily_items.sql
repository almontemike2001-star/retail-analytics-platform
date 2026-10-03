with completed_items as (

    select
        order_item_id,
        order_id,
        store_id,
        store_sk,
        business_date,
        quantity,
        line_total,
        line_cost,
        gross_margin
    from {{ ref('fct_order_items') }}
    where order_status = 'completed'

),

daily as (

    select
        store_id,
        store_sk,
        business_date,

        sum(quantity) as product_quantity,
        sum(line_total) as item_sales,
        sum(line_cost) as total_cost,
        sum(gross_margin) as gross_margin

    from completed_items

    group by
        store_id,
        store_sk,
        business_date

)

select *
from daily
