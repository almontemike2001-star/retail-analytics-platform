with completed_items as (

    select
        i.order_item_id,
        i.order_id,
        i.business_date,

        i.store_id,
        i.store_sk,

        i.product_id,
        i.product_sk,

        i.quantity,
        i.unit_price,
        i.line_discount,
        i.line_total,

        i.historical_unit_cost,
        i.line_cost,
        i.gross_margin

    from {{ ref('fct_order_items') }} i

    where i.order_status = 'completed'

),

aggregated as (

    select
        business_date,
        product_sk,
        product_id,

        count(distinct order_id) as transaction_count,
        count(*) as order_line_count,

        sum(quantity) as product_quantity,

        sum(line_discount) as discount_amount,
        sum(line_total) as product_sales,
        sum(line_cost) as total_cost,
        sum(gross_margin) as gross_margin

    from completed_items

    group by
        business_date,
        product_sk,
        product_id

),

final as (

    select
        concat(
            cast(a.business_date as string),
            '-',
            a.product_sk
        ) as product_day_key,

        d.date_key,
        a.business_date,

        d.year,
        d.quarter,
        d.month_number,
        d.month_name,
        d.iso_year,
        d.iso_week,
        d.day_name,
        d.is_weekend,

        a.product_sk,
        a.product_id,

        p.sku,
        p.product_name,
        p.size,

        p.category_id,
        p.category_name,
        p.category_group,

        p.base_price,
        p.unit_cost,

        a.transaction_count,
        a.order_line_count,
        a.product_quantity,

        a.discount_amount,
        a.product_sales,
        a.total_cost,
        a.gross_margin,

        round(
            safe_divide(
                a.product_sales,
                nullif(a.product_quantity, 0)
            ),
            2
        ) as average_selling_price,

        round(
            safe_divide(
                a.product_quantity,
                nullif(a.transaction_count, 0)
            ),
            4
        ) as avg_units_per_transaction,

        round(
            safe_divide(
                a.gross_margin,
                nullif(a.product_sales, 0)
            ),
            4
        ) as gross_margin_rate

    from aggregated a

    inner join {{ ref('dim_product') }} p
        on a.product_sk = p.product_sk

    inner join {{ ref('dim_date') }} d
        on a.business_date = d.calendar_date

)

select *
from final
