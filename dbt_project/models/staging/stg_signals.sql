-- Typed staging layer on top of the raw Parquet files written by the simulator
-- (or by the OPC UA collector). One row per machine and 10 s sample.
select
    scenario || '|' || machine_id || '|' || strftime(cast(ts as timestamp), '%Y-%m-%dT%H:%M:%S') as sample_id,
    scenario,
    cast(ts as timestamp)            as ts,
    machine_id,
    state,
    cast(temp_c as double)           as temp_c,
    cast(vibration_mm_s as double)   as vibration_mm_s,
    cast(motor_current_a as double)  as motor_current_a,
    cast(cycle_time_s as double)     as cycle_time_s,
    cast(rejects_per_min as double)  as rejects_per_min
from read_parquet('{{ env_var("PLANTOPS_RAW_DIR", "data/raw") }}/*.parquet')
