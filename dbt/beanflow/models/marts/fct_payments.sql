with latest_payments as (

    select *
    from {{ ref('stg_payments') }}
    qualify row_number() over (
        partition by payment_id
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
        p.payment_id,
        p.order_id,

        o.business_date,
        o.order_ts,

        o.store_id,
        o.store_sk,
        o.customer_id,

        p.payment_method,
        p.amount,
        p.payment_status,
        p.paid_at,
        p.updated_at

    from latest_payments p

    left join {{ ref('fct_orders') }} o
        on p.order_id = o.order_id

)

select *
from final
