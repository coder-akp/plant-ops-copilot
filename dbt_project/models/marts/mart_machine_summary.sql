-- One row per scenario and machine: availability, fault behaviour and
-- operating statistics while the machine was running.
with states as (
    select
        scenario,
        machine_id,
        sum(duration_s)                                              as total_s,
        sum(case when state = 'RUN'   then duration_s else 0 end)    as run_s,
        sum(case when state = 'IDLE'  then duration_s else 0 end)    as idle_s,
        sum(case when state = 'FAULT' then duration_s else 0 end)    as fault_s,
        sum(case when state = 'CLEAN' then duration_s else 0 end)    as clean_s,
        count(case when state = 'FAULT' then 1 end)                  as fault_events,
        coalesce(max(case when state = 'FAULT' then duration_s end), 0) as longest_fault_s
    from {{ ref('int_state_runs') }}
    group by scenario, machine_id
),

running as (
    select
        scenario,
        machine_id,
        avg(temp_c)               as avg_temp_c,
        max(temp_c)               as max_temp_c,
        avg(vibration_mm_s)       as avg_vibration_mm_s,
        max(vibration_mm_s)       as max_vibration_mm_s,
        avg(motor_current_a)      as avg_motor_current_a,
        max(motor_current_a)      as max_motor_current_a,
        avg(cycle_time_s)         as avg_cycle_time_s,
        sum(rejects_per_min) * {{ var("sample_seconds") }} / 60.0 as total_rejects
    from {{ ref('stg_signals') }}
    where state = 'RUN'
    group by scenario, machine_id
)

select
    s.scenario,
    s.machine_id,
    s.total_s,
    s.run_s,
    s.idle_s,
    s.fault_s,
    s.clean_s,
    s.fault_events,
    s.longest_fault_s,
    round(100.0 * s.run_s / nullif(s.total_s - s.clean_s, 0), 1) as availability_pct,
    round(r.avg_temp_c, 2)             as avg_temp_c,
    round(r.max_temp_c, 2)             as max_temp_c,
    round(r.avg_vibration_mm_s, 3)     as avg_vibration_mm_s,
    round(r.max_vibration_mm_s, 3)     as max_vibration_mm_s,
    round(r.avg_motor_current_a, 3)    as avg_motor_current_a,
    round(r.max_motor_current_a, 3)    as max_motor_current_a,
    round(r.avg_cycle_time_s, 3)       as avg_cycle_time_s,
    round(r.total_rejects, 1)          as total_rejects
from states s
left join running r using (scenario, machine_id)
