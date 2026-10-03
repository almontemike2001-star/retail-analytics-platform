with daily_fact as (

    select
        round(sum(total_sales), 2) as total_sales,
        sum(transaction_count) as transaction_count
    from {{ ref('fct_store_daily_sales') }}

),

orders as (

    select
        round(sum(total_amount), 2) as total_sales,
        count(*) as transaction_count
    from {{ ref('fct_orders') }}
    where order_status = 'completed'

)

select
    d.total_sales as daily_fact_sales,
    o.total_sales as order_sales,
    d.transaction_count as daily_fact_transactions,
    o.transaction_count as order_transactions
from daily_fact d
cross join orders o
where d.total_sales != o.total_sales
   or d.transaction_count != o.transaction_count
