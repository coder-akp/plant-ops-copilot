"""Read-only access to the dbt-built DuckDB database."""
from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from sim.line import SCENARIOS

_lock = threading.Lock()
_con: duckdb.DuckDBPyConnection | None = None
_con_path: Path | None = None


def configure(db_path: Path) -> None:
    """Open the database, replacing any existing connection. Call once at startup and in tests."""
    global _con, _con_path
    with _lock:
        if _con is not None:
            _con.close()
        _con = duckdb.connect(str(db_path), read_only=True)
        _con_path = Path(db_path)
    scenario_frame.cache_clear()
    _kpi_cache.cache_clear()


def _cursor() -> duckdb.DuckDBPyConnection:
    if _con is None:
        raise RuntimeError("database not configured; call app.data.configure(path) first")
    with _lock:
        return _con.cursor()


def available_scenarios() -> list[str]:
    cur = _cursor()
    rows = cur.execute("select distinct scenario from stg_signals order by 1").fetchall()
    present = {r[0] for r in rows}
    ordered = [s for s in SCENARIOS if s in present]
    return ordered + sorted(present - set(ordered))


@lru_cache(maxsize=8)
def scenario_frame(scenario: str) -> pd.DataFrame:
    cur = _cursor()
    df = cur.execute(
        "select ts, machine_id, state, temp_c, vibration_mm_s, motor_current_a, cycle_time_s, rejects_per_min "
        "from stg_signals where scenario = ? order by ts, machine_id",
        [scenario],
    ).df()
    if df.empty:
        raise KeyError(f"unknown scenario {scenario!r}")
    return df


@lru_cache(maxsize=8)
def _kpi_cache(scenario: str) -> tuple:
    cur = _cursor()
    df = cur.execute(
        "select * exclude (scenario) from mart_machine_summary where scenario = ? order by machine_id",
        [scenario],
    ).df()
    return tuple(df.to_dict(orient="records"))


def machine_kpis(scenario: str, machine_id: str | None = None) -> list[dict]:
    rows = list(_kpi_cache(scenario))
    if machine_id is not None:
        rows = [r for r in rows if r["machine_id"] == machine_id]
    return [{k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in r.items()} for r in rows]


def state_runs(scenario: str, machine_id: str, min_duration_s: int = 0) -> list[dict]:
    cur = _cursor()
    df = cur.execute(
        "select state, strftime(run_start, '%Y-%m-%dT%H:%M:%S') as start, strftime(run_end, '%Y-%m-%dT%H:%M:%S') as \"end\", "
        "duration_s from int_state_runs where scenario = ? and machine_id = ? and state <> 'RUN' and duration_s >= ? "
        "order by run_start",
        [scenario, machine_id, min_duration_s],
    ).df()
    return df.to_dict(orient="records")
