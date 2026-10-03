with rfm as (

    select
        sum(frequency) as transaction_count,
        round(sum(monetary), 2) as total_sales

    from {{ ref('customer_rfm') }}

),

completed_orders as (

    select
        count(distinct order_id) as transaction_count,
        round(sum(total_amount), 2) as total_sales

    from {{ ref('fct_orders') }}

    where order_status = 'completed'
      and customer_id is not null

)

select
    r.transaction_count as rfm_transactions,
    o.transaction_count as fact_transactions,

    r.total_sales as rfm_sales,
    o.total_sales as fact_sales

from rfm r
cross join completed_orders o

where r.transaction_count != o.transaction_count
   or r.total_sales != o.total_sales
