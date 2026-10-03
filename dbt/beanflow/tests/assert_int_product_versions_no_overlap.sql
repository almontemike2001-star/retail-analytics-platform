select
    a.product_id,
    a.valid_from,
    a.valid_to,
    b.valid_from as next_valid_from,
    b.valid_to as next_valid_to
from {{ ref('int_product_versions') }} a
join {{ ref('int_product_versions') }} b
  on a.product_id = b.product_id
 and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
 and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
 and a.valid_from != b.valid_from
