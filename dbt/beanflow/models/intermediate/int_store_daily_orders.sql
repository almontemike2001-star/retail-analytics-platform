with completed_orders as (

    select
        order_id,
        store_id,
        store_sk,
        business_date,
        subtotal,
        discount_amount,
        tax_amount,
        total_amount
    from {{ ref('fct_orders') }}
    where order_status = 'completed'

),

daily as (

    select
        store_id,
        store_sk,
        business_date,

        count(*) as transaction_count,

        sum(subtotal) as subtotal,
        sum(discount_amount) as discount_amount,
        sum(tax_amount) as tax_amount,
        sum(total_amount) as total_sales

    from completed_orders

    group by
        store_id,
        store_sk,
        business_date

)

select *
from daily
