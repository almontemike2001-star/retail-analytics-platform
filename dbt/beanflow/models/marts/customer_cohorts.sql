with completed_orders as (

    select
        order_id,
        customer_id,
        business_date,
        total_amount

    from {{ ref('fct_orders') }}

    where order_status = 'completed'
      and customer_id is not null

),

customer_first_purchase as (

    select
        customer_id,
        min(business_date) as first_purchase_date,
        date_trunc(
            min(business_date),
            month
        ) as cohort_month

    from completed_orders

    group by customer_id

),

customer_monthly_activity as (

    select
        customer_id,
        date_trunc(business_date, month) as activity_month,

        count(distinct order_id) as transaction_count,
        sum(total_amount) as total_sales

    from completed_orders

    group by
        customer_id,
        activity_month

),

cohort_activity as (

    select
        a.customer_id,

        f.first_purchase_date,
        f.cohort_month,

        a.activity_month,

        date_diff(
            a.activity_month,
            f.cohort_month,
            month
        ) as month_number,

        a.transaction_count,
        a.total_sales

    from customer_monthly_activity a

    inner join customer_first_purchase f
        on a.customer_id = f.customer_id

),

cohort_sizes as (

    select
        cohort_month,
        count(distinct customer_id) as cohort_size

    from customer_first_purchase

    group by cohort_month

),

aggregated as (

    select
        c.cohort_month,
        c.activity_month,
        c.month_number,

        s.cohort_size,

        count(distinct c.customer_id) as active_customers,

        sum(c.transaction_count) as transaction_count,
        sum(c.total_sales) as total_sales

    from cohort_activity c

    inner join cohort_sizes s
        on c.cohort_month = s.cohort_month

    group by
        c.cohort_month,
        c.activity_month,
        c.month_number,
        s.cohort_size

)

select
    concat(
        cast(cohort_month as string),
        '-',
        cast(month_number as string)
    ) as cohort_month_key,

    cohort_month,
    activity_month,
    month_number,

    cohort_size,
    active_customers,

    transaction_count,
    total_sales,

    round(
        safe_divide(
            active_customers,
            cohort_size
        ),
        4
    ) as retention_rate,

    round(
        safe_divide(
            total_sales,
            active_customers
        ),
        2
    ) as sales_per_active_customer

from aggregated
