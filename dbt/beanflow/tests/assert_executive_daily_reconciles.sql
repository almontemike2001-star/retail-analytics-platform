with executive as (

    select
        round(sum(total_sales), 2) as total_sales,
        sum(transaction_count) as transaction_count,
        sum(product_quantity) as product_quantity
    from {{ ref('executive_daily') }}

),

daily_fact as (

    select
        round(sum(total_sales), 2) as total_sales,
        sum(transaction_count) as transaction_count,
        sum(product_quantity) as product_quantity
    from {{ ref('fct_store_daily_sales') }}

)

select
    e.total_sales as executive_sales,
    f.total_sales as fact_sales,

    e.transaction_count as executive_transactions,
    f.transaction_count as fact_transactions,

    e.product_quantity as executive_quantity,
    f.product_quantity as fact_quantity

from executive e
cross join daily_fact f

where e.total_sales != f.total_sales
   or e.transaction_count != f.transaction_count
   or e.product_quantity != f.product_quantity
