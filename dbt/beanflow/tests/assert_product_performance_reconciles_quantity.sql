with product_mart as (

    select
        sum(product_quantity) as product_quantity
    from {{ ref('product_performance') }}

),

items as (

    select
        sum(quantity) as product_quantity
    from {{ ref('fct_order_items') }}
    where order_status = 'completed'

)

select
    p.product_quantity as mart_quantity,
    i.product_quantity as fact_quantity

from product_mart p
cross join items i

where p.product_quantity != i.product_quantity
