with latest_items as (

    select *
    from {{ ref('stg_order_items') }}
    qualify row_number() over (
        partition by order_item_id
        order by
            updated_at desc,
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

),

final as (

    select
        i.order_item_id,
        i.order_id,

        o.business_date,
        o.order_ts,

        o.store_id,
        o.store_sk,

        o.customer_id,
        o.promotion_id,
        o.order_status,
        o.order_channel,

        i.product_id,
        p.product_sk,

        i.quantity,
        i.unit_price,
        i.line_discount,
        i.line_total,

        p.unit_cost as historical_unit_cost,

        round(
            p.unit_cost * i.quantity,
            2
        ) as line_cost,

        round(
            i.line_total - (p.unit_cost * i.quantity),
            2
        ) as gross_margin,

        i.updated_at

    from latest_items i

    inner join {{ ref('fct_orders') }} o
        on i.order_id = o.order_id

    left join {{ ref('dim_product') }} p
        on i.product_id = p.product_id
       and o.order_ts >= p.valid_from
       and (
            o.order_ts < p.valid_to
            or p.valid_to is null
       )

)

select *
from final
