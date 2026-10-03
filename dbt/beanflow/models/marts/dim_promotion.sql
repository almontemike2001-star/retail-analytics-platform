with latest_promotions as (

    select *
    from {{ ref('stg_promotions') }}
    qualify row_number() over (
        partition by promotion_id
        order by
            updated_at desc,
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    to_hex(md5(cast(promotion_id as string))) as promotion_sk,

    promotion_id,
    promo_code,
    promo_name,
    promo_type,
    discount_value,
    min_order_amount,
    start_date,
    end_date,
    updated_at

from latest_promotions
