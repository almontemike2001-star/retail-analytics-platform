select
    customer_id,
    count(*) as row_count
from {{ ref('dim_customer') }}
group by customer_id
having count(*) != 1
