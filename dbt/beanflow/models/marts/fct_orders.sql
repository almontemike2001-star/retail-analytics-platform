with latest_orders as (

    select *
    from {{ ref('stg_orders') }}
    qualify row_number() over (
        partition by order_id
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
        o.order_id,
        o.order_number,

        o.store_id,
        s.store_sk,

        o.customer_id,
        o.promotion_id,

        o.order_ts,
        date(o.order_ts, 'Asia/Manila') as business_date,

        o.order_channel,
        o.order_status,

        o.subtotal,
        o.discount_amount,
        o.tax_amount,
        o.total_amount,

        o.updated_at

    from latest_orders o

    left join {{ ref('dim_store') }} s
        on o.store_id = s.store_id
       and o.order_ts >= s.valid_from
       and (
            o.order_ts < s.valid_to
            or s.valid_to is null
       )

)

select *
from final
