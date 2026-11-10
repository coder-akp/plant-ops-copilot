-- Singular test: availability must be a valid percentage.
select *
from {{ ref('mart_machine_summary') }}
where availability_pct < 0 or availability_pct > 100
