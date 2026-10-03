with product_mart as (

    select
        round(sum(product_sales), 2) as product_sales,
        round(sum(total_cost), 2) as total_cost,
        round(sum(gross_margin), 2) as gross_margin
    from {{ ref('product_performance') }}

),

items as (

    select
        round(sum(line_total), 2) as product_sales,
        round(sum(line_cost), 2) as total_cost,
        round(sum(gross_margin), 2) as gross_margin
    from {{ ref('fct_order_items') }}
    where order_status = 'completed'

)

select
    p.product_sales as mart_sales,
    i.product_sales as fact_sales,

    p.total_cost as mart_cost,
    i.total_cost as fact_cost,

    p.gross_margin as mart_margin,
    i.gross_margin as fact_margin

from product_mart p
cross join items i

where p.product_sales != i.product_sales
   or p.total_cost != i.total_cost
   or p.gross_margin != i.gross_margin
