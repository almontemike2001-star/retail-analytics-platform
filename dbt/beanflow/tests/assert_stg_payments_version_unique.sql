select
    payment_id,
    updated_at,
    count(*) as row_count
from {{ ref('stg_payments') }}
group by payment_id, updated_at
having count(*) > 1
