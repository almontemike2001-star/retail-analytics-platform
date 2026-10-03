select
    product_day_key,
    product_id,
    business_date,

    average_selling_price,
    avg_units_per_transaction,
    gross_margin_rate

from {{ ref('product_performance') }}

where abs(
        average_selling_price
        - round(
            safe_divide(
                product_sales,
                nullif(product_quantity, 0)
            ),
            2
        )
      ) > 0.01

   or abs(
        avg_units_per_transaction
        - round(
            safe_divide(
                product_quantity,
                nullif(transaction_count, 0)
            ),
            4
        )
      ) > 0.0001

   or abs(
        gross_margin_rate
        - round(
            safe_divide(
                gross_margin,
                nullif(product_sales, 0)
            ),
            4
        )
      ) > 0.0001
