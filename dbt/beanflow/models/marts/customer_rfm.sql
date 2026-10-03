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

analysis_date as (

    select
        max(business_date) as as_of_date

    from completed_orders

),

customer_metrics as (

    select
        o.customer_id,

        min(o.business_date) as first_purchase_date,
        max(o.business_date) as last_purchase_date,

        date_diff(
            a.as_of_date,
            max(o.business_date),
            day
        ) as recency_days,

        count(distinct o.order_id) as frequency,

        round(
            sum(o.total_amount),
            2
        ) as monetary,

        round(
            safe_divide(
                sum(o.total_amount),
                count(distinct o.order_id)
            ),
            2
        ) as average_order_value,

        a.as_of_date

    from completed_orders o

    cross join analysis_date a

    group by
        o.customer_id,
        a.as_of_date

),

scored as (

    select
        *,

        ntile(5) over (
            order by recency_days desc
        ) as recency_score,

        ntile(5) over (
            order by frequency asc
        ) as frequency_score,

        ntile(5) over (
            order by monetary asc
        ) as monetary_score

    from customer_metrics

),

with_customer as (

    select
        s.customer_id,
        c.customer_sk,

        c.full_name,
        c.city,
        c.loyalty_tier,
        c.signup_date,

        s.as_of_date,
        s.first_purchase_date,
        s.last_purchase_date,

        s.recency_days,
        s.frequency,
        s.monetary,
        s.average_order_value,

        s.recency_score,
        s.frequency_score,
        s.monetary_score,

        concat(
            cast(s.recency_score as string),
            cast(s.frequency_score as string),
            cast(s.monetary_score as string)
        ) as rfm_score,

        s.recency_score
            + s.frequency_score
            + s.monetary_score as rfm_total_score

    from scored s

    inner join {{ ref('dim_customer') }} c
        on s.customer_id = c.customer_id

),

final as (

    select
        *,

        case
            when recency_score >= 4
             and frequency_score >= 4
             and monetary_score >= 4
                then 'Champions'

            when recency_score >= 3
             and frequency_score >= 4
                then 'Loyal Customers'

            when recency_score >= 4
             and frequency_score between 2 and 3
                then 'Potential Loyalists'

            when recency_score = 5
             and frequency_score = 1
                then 'New Customers'

            when recency_score <= 2
             and frequency_score >= 3
                then 'At Risk'

            when recency_score <= 2
             and frequency_score <= 2
                then 'Hibernating'

            else 'Needs Attention'
        end as customer_segment

    from with_customer

)

select *
from final
