with performance as (

    select
        count(*) as row_count,
        round(sum(total_sales), 2) as total_sales,
        sum(transaction_count) as transaction_count,
        sum(product_quantity) as product_quantity
    from {{ ref('store_performance') }}

),

daily_fact as (

    select
        count(*) as row_count,
        round(sum(total_sales), 2) as total_sales,
        sum(transaction_count) as transaction_count,
        sum(product_quantity) as product_quantity
    from {{ ref('fct_store_daily_sales') }}

)

select
    p.row_count as performance_rows,
    f.row_count as fact_rows,

    p.total_sales as performance_sales,
    f.total_sales as fact_sales,

    p.transaction_count as performance_transactions,
    f.transaction_count as fact_transactions,

    p.product_quantity as performance_quantity,
    f.product_quantity as fact_quantity

from performance p
cross join daily_fact f

where p.row_count != f.row_count
   or p.total_sales != f.total_sales
   or p.transaction_count != f.transaction_count
   or p.product_quantity != f.product_quantity
