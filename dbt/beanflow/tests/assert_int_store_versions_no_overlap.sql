select
    a.store_id,
    a.valid_from,
    a.valid_to,
    b.valid_from as next_valid_from,
    b.valid_to as next_valid_to
from {{ ref('int_store_versions') }} a
join {{ ref('int_store_versions') }} b
  on a.store_id = b.store_id
 and a.valid_from < coalesce(b.valid_to, timestamp('9999-12-31'))
 and b.valid_from < coalesce(a.valid_to, timestamp('9999-12-31'))
 and a.valid_from != b.valid_from
