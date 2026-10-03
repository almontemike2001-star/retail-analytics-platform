select
    business_date,

    total_sales,
    transaction_count,
    product_quantity,
    store_days,

    aov,
    ads,
    adq

from {{ ref('executive_daily') }}

where abs(
        aov
        - round(
            safe_divide(total_sales, nullif(transaction_count, 0)),
            2
        )
      ) > 0.01

   or abs(
        ads
        - round(
            safe_divide(total_sales, nullif(store_days, 0)),
            2
        )
      ) > 0.01

   or abs(
        adq
        - round(
            safe_divide(product_quantity, nullif(store_days, 0)),
            4
        )
      ) > 0.0001
