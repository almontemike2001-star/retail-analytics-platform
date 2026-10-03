with daily_fact as (

    select
        sum(product_quantity) as product_quantity
    from {{ ref('fct_store_daily_sales') }}

),

items as (

    select
        sum(quantity) as product_quantity
    from {{ ref('fct_order_items') }}
    where order_status = 'completed'

)

select
    d.product_quantity as daily_fact_quantity,
    i.product_quantity as order_item_quantity
from daily_fact d
cross join items i
where d.product_quantity != i.product_quantity
