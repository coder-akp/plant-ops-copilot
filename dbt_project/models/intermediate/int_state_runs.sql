-- Gaps-and-islands: collapses consecutive samples with the same machine state
-- into runs (start, end, duration). Used for dwell-time and fault KPIs.
with ordered as (
    select
        scenario,
        machine_id,
        ts,
        state,
        lag(state) over (partition by scenario, machine_id order by ts) as prev_state
    from {{ ref('stg_signals') }}
),

flagged as (
    select
        *,
        case when prev_state is null or prev_state <> state then 1 else 0 end as is_new_run
    from ordered
),

grouped as (
    select
        *,
        sum(is_new_run) over (
            partition by scenario, machine_id
            order by ts
            rows between unbounded preceding and current row
        ) as run_no
    from flagged
)

select
    scenario,
    machine_id,
    run_no,
    state,
    min(ts)                                         as run_start,
    max(ts) + interval '{{ var("sample_seconds") }} seconds' as run_end,
    count(*) * {{ var("sample_seconds") }}          as duration_s
from grouped
group by scenario, machine_id, run_no, state
