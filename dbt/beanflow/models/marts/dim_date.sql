with date_bounds as (

    select
        min(business_date) as min_date,
        max(business_date) as max_date
    from {{ ref('fct_orders') }}

),

calendar as (

    select date_day
    from date_bounds,
    unnest(
        generate_date_array(min_date, max_date)
    ) as date_day

)

select
    cast(format_date('%Y%m%d', date_day) as int64) as date_key,

    date_day as calendar_date,

    extract(year from date_day) as year,
    extract(quarter from date_day) as quarter,
    extract(month from date_day) as month_number,
    format_date('%B', date_day) as month_name,

    extract(isoyear from date_day) as iso_year,
    extract(isoweek from date_day) as iso_week,

    extract(day from date_day) as day_of_month,
    extract(dayofweek from date_day) as day_of_week_number,
    format_date('%A', date_day) as day_name,

    date_trunc(date_day, week(monday)) as week_start_date,
    date_trunc(date_day, month) as month_start_date,
    date_trunc(date_day, quarter) as quarter_start_date,
    date_trunc(date_day, year) as year_start_date,

    extract(dayofweek from date_day) in (1, 7) as is_weekend

from calendar
