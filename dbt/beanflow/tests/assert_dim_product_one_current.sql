select
    product_id,
    countif(is_current) as current_versions
from {{ ref('dim_product') }}
group by product_id
having countif(is_current) != 1
