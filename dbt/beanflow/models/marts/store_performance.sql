with store_daily as (

    select *
    from {{ ref('fct_store_daily_sales') }}

),

final as (

    select
        f.store_day_key,

        d.date_key,
        f.business_date,

        d.year,
        d.quarter,
        d.month_number,
        d.month_name,
        d.iso_year,
        d.iso_week,
        d.day_name,
        d.is_weekend,

        f.store_sk,
        f.store_id,

        s.store_code,
        s.store_name,
        s.store_type,
        s.city,

        s.area_id,
        s.area_name,

        s.region_id,
        s.region_name,

        f.transaction_count,
        f.product_quantity,

        f.subtotal,
        f.discount_amount,
        f.tax_amount,
        f.total_sales,

        f.item_sales,
        f.total_cost,
        f.gross_margin,

        f.aov,

        f.total_sales as daily_sales,
        f.product_quantity as daily_quantity,

        round(
            safe_divide(
                f.gross_margin,
                nullif(f.item_sales, 0)
            ),
            4
        ) as gross_margin_rate,

        f.is_open_day

    from store_daily f

    inner join {{ ref('dim_store') }} s
        on f.store_sk = s.store_sk

    inner join {{ ref('dim_date') }} d
        on f.business_date = d.calendar_date

)

select *
from final
