with minutes as (

    select minute_of_day
    from unnest(generate_array(0, 1439)) as minute_of_day

),

final as (

    select
        minute_of_day as time_key,

        div(minute_of_day, 60) as hour_24,
        mod(minute_of_day, 60) as minute,

        time(
            div(minute_of_day, 60),
            mod(minute_of_day, 60),
            0
        ) as time_value,

        format_time(
            '%H:%M',
            time(
                div(minute_of_day, 60),
                mod(minute_of_day, 60),
                0
            )
        ) as time_label,

        case
            when div(minute_of_day, 60) between 5 and 10 then 'Morning'
            when div(minute_of_day, 60) between 11 and 13 then 'Lunch'
            when div(minute_of_day, 60) between 14 and 16 then 'Afternoon'
            when div(minute_of_day, 60) between 17 and 20 then 'Evening'
            else 'Late Night'
        end as daypart

    from minutes

)

select *
from final
