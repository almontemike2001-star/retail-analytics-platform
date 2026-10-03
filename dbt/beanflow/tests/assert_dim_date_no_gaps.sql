with ordered_dates as (

    select
        calendar_date,
        lag(calendar_date) over (
            order by calendar_date
        ) as previous_date

    from {{ ref('dim_date') }}

)

select
    calendar_date,
    previous_date
from ordered_dates
where previous_date is not null
  and date_diff(calendar_date, previous_date, day) != 1
