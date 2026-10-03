with latest_customers as (

    select *
    from {{ ref('stg_customers') }}
    qualify row_number() over (
        partition by customer_id
        order by
            updated_at desc,
            _ingestion_date desc,
            _loaded_at desc,
            _extracted_at desc,
            _extract_batch_id desc
    ) = 1

)

select
    to_hex(md5(cast(customer_id as string))) as customer_sk,

    customer_id,
    full_name,
    email,
    phone,
    birth_date,
    gender,
    city,
    signup_date,
    signup_store_id,
    loyalty_tier,
    updated_at

from latest_customers
