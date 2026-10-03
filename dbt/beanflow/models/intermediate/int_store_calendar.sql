with date_bounds as (

    select
        min(business_date) as min_date,
        max(business_date) as max_date
    from {{ ref('fct_orders') }}

),

calendar as (

    select calendar_date
    from date_bounds,
    unnest(
        generate_date_array(min_date, max_date)
    ) as calendar_date

),

store_versions as (

    select
        store_sk,
        store_id,
        area_id,
        store_code,
        store_name,
        store_type,
        city,
        opened_date,
        closed_date,
        status,
        valid_from,
        valid_to
    from {{ ref('dim_store') }}

),

store_calendar as (

    select
        s.store_sk,
        s.store_id,
        s.area_id,
        s.store_code,
        s.store_name,
        s.store_type,
        s.city,
        c.calendar_date as business_date

    from calendar c

    inner join store_versions s
        on c.calendar_date >= s.opened_date

       and (
            s.closed_date is null
            or c.calendar_date <= s.closed_date
       )

       and timestamp(c.calendar_date, 'Asia/Manila') >= s.valid_from

       and (
            timestamp(c.calendar_date, 'Asia/Manila') < s.valid_to
            or s.valid_to is null
       )

)

select *
from store_calendar
