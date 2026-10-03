with daily_sales as (

    select
        business_date,

        count(distinct store_day_key) as store_days,
        count(distinct store_id) as active_stores,

        sum(transaction_count) as transaction_count,
        sum(product_quantity) as product_quantity,

        sum(subtotal) as subtotal,
        sum(discount_amount) as discount_amount,
        sum(tax_amount) as tax_amount,
        sum(total_sales) as total_sales,

        sum(item_sales) as item_sales,
        sum(total_cost) as total_cost,
        sum(gross_margin) as gross_margin

    from {{ ref('fct_store_daily_sales') }}

    group by business_date

),

final as (

    select
        d.date_key,
        d.calendar_date as business_date,

        d.year,
        d.quarter,
        d.month_number,
        d.month_name,
        d.iso_year,
        d.iso_week,
        d.day_of_month,
        d.day_of_week_number,
        d.day_name,
        d.is_weekend,

        s.active_stores,
        s.store_days,

        s.transaction_count,
        s.product_quantity,

        s.subtotal,
        s.discount_amount,
        s.tax_amount,
        s.total_sales,

        s.item_sales,
        s.total_cost,
        s.gross_margin,

        round(
            safe_divide(
                s.total_sales,
                nullif(s.transaction_count, 0)
            ),
            2
        ) as aov,

        round(
            safe_divide(
                s.total_sales,
                nullif(s.store_days, 0)
            ),
            2
        ) as ads,

        round(
            safe_divide(
                s.product_quantity,
                nullif(s.store_days, 0)
            ),
            4
        ) as adq,

        round(
            safe_divide(
                s.gross_margin,
                nullif(s.item_sales, 0)
            ),
            4
        ) as gross_margin_rate

    from daily_sales s

    inner join {{ ref('dim_date') }} d
        on s.business_date = d.calendar_date

)

select *
from final
