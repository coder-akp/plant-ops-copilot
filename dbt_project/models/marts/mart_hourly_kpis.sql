-- Hourly KPI trend per scenario and machine (statistics over RUN samples only).
select
    scenario,
    machine_id,
    date_trunc('hour', ts)                                              as hour_start,
    round(100.0 * count(*) filter (where state = 'RUN') / count(*), 1)  as run_pct,
    count(*) filter (where state = 'FAULT') * {{ var("sample_seconds") }} as fault_s,
    round(avg(temp_c)          filter (where state = 'RUN'), 2)         as avg_temp_c,
    round(max(temp_c)          filter (where state = 'RUN'), 2)         as max_temp_c,
    round(avg(vibration_mm_s)  filter (where state = 'RUN'), 3)         as avg_vibration_mm_s,
    round(max(vibration_mm_s)  filter (where state = 'RUN'), 3)         as max_vibration_mm_s,
    round(avg(motor_current_a) filter (where state = 'RUN'), 3)         as avg_motor_current_a,
    round(avg(cycle_time_s)    filter (where state = 'RUN'), 3)         as avg_cycle_time_s,
    count(temp_c) filter (where state = 'RUN')                          as temp_samples,
    count(*) filter (where state = 'RUN')                               as run_samples
from {{ ref('stg_signals') }}
group by scenario, machine_id, date_trunc('hour', ts)
