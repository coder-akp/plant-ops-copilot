"""Tools available to the agents.

Design rules that keep the system cheap and reliable:
* Tools take as few arguments as possible. The scenario and run id come from the
  ADK session state, so the model cannot get them wrong.
* All heavy computation (statistics, ML, SQL) is deterministic Python, not LLM work.
* Results are compact JSON. Errors are returned as {"error": ...} so that the model
  can recover and the run does not crash.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from google.adk.tools import ToolContext

from app import data, detect, rag, workorders
from sim.line import MACHINES

VALID_SIGNALS = detect.SIGNALS


@lru_cache(maxsize=8)
def _scan_cached(scenario: str, include_windows: bool) -> dict[str, Any]:
    return detect.scan(data.scenario_frame(scenario), include_windows=include_windows)


def scan_for_scenario(scenario: str, include_windows: bool = False) -> dict[str, Any]:
    """Return a cached scan as a deep copy that is safe to mutate. Used by the tools and the web API."""
    return copy.deepcopy(_scan_cached(scenario, include_windows))


def clear_caches() -> None:
    _scan_cached.cache_clear()


def _scenario(ctx: ToolContext) -> str:
    return str(ctx.state["scenario_id"])


def scan_line(tool_context: ToolContext) -> dict:
    """Scan all machines of the line for abnormal behaviour in the current shift.

    Runs the statistical and machine-learning detectors (baseline drift,
    alarm-limit checks, stuck sensors, signal dropouts, Isolation Forest) and
    returns the findings ranked by severity (0-100). Call this first.
    An empty findings list means the line looks healthy.
    """
    try:
        return scan_for_scenario(_scenario(tool_context))
    except Exception as exc:  # noqa: BLE001 - report any failure to the model
        return {"error": str(exc)}


def get_signal_trend(machine_id: str, signal: str, tool_context: ToolContext) -> dict:
    """Get the hourly average and maximum of one signal of one machine, plus its alarm limits.

    Args:
        machine_id: Machine identifier, one of FILLER-01, CAPPER-01, LABELER-01, PACKER-01.
        signal: One of temp_c, vibration_mm_s, motor_current_a, cycle_time_s, rejects_per_min.
    """
    if machine_id not in MACHINES:
        return {"error": f"unknown machine_id {machine_id!r}; valid: {MACHINES}"}
    if signal not in VALID_SIGNALS:
        return {"error": f"unknown signal {signal!r}; valid: {VALID_SIGNALS}"}
    try:
        return detect.hourly_trend(data.scenario_frame(_scenario(tool_context)), machine_id, signal)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def get_machine_kpis(machine_id: str, tool_context: ToolContext) -> dict:
    """Get availability and stop statistics for one machine (from the dbt marts).

    Returns availability %, number and length of fault events, and the list of
    non-running periods longer than one minute.

    Args:
        machine_id: Machine identifier, one of FILLER-01, CAPPER-01, LABELER-01, PACKER-01.
    """
    if machine_id not in MACHINES:
        return {"error": f"unknown machine_id {machine_id!r}; valid: {MACHINES}"}
    try:
        scenario = _scenario(tool_context)
        rows = data.machine_kpis(scenario, machine_id)
        kpi = rows[0] if rows else {}
        keep = ["availability_pct", "fault_events", "longest_fault_s", "fault_s", "idle_s", "clean_s",
                "avg_temp_c", "max_temp_c", "max_vibration_mm_s", "max_motor_current_a", "total_rejects"]
        runs = data.state_runs(scenario, machine_id, min_duration_s=60)
        stops = [{"state": r["state"], "from": r["start"][11:16], "minutes": round(r["duration_s"] / 60, 1)}
                 for r in runs if r["state"] != "CLEAN"][:10]
        return {"machine_id": machine_id, **{k: kpi.get(k) for k in keep}, "stops_over_1min": stops}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def search_manuals(query: str, machine_id: str = "", tool_context: ToolContext = None) -> dict:
    """Search the maintenance manuals and SOPs for passages relevant to a query.

    Returns up to 3 passages, each with a citable source id such as "MNT-101 §3".
    Use short, specific queries, for example "bearing wear vibration drift" or
    "stuck temperature sensor flatline".

    Args:
        query: Free-text search query. Describe the observed symptom, e.g. "temperature rises to trip limit repeated thermal trips".
        machine_id: Machine the finding is about (e.g. CAPPER-01). Manuals written for other machines are then excluded.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty query"}
    machine = (machine_id or "").strip().upper() or None
    return {"query": query, "machine_id": machine, "results": rag.search(query, top_k=3, machine_id=machine)}


def propose_work_order(machine_id: str, priority: str, title: str, evidence: str,
                       suspected_cause: str, recommended_action: str,
                       tool_context: ToolContext) -> dict:
    """Propose a maintenance work order. It is NOT executed; a human must approve it.

    Args:
        machine_id: Machine identifier, one of FILLER-01, CAPPER-01, LABELER-01, PACKER-01.
        priority: P1, P2, P3 or P4 according to the priority matrix (MNT-105).
        title: Short title, max 100 characters.
        evidence: Key numbers and times that support the order.
        suspected_cause: Most likely root cause.
        recommended_action: Concrete next step for the maintenance team.
    """
    if machine_id not in MACHINES:
        return {"error": f"unknown machine_id {machine_id!r}; valid: {MACHINES}"}
    try:
        wo = workorders.propose(
            run_id=str(tool_context.state.get("run_id", "local")),
            machine_id=machine_id,
            priority=priority,
            title=title,
            evidence=evidence,
            suspected_cause=suspected_cause,
            recommended_action=recommended_action,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    return {"status": "pending_approval", "work_order": wo.to_dict()}


DETECTION_TOOLS = [scan_line, get_signal_trend]
DIAGNOSIS_TOOLS = [search_manuals, get_machine_kpis]
REPORT_TOOLS = [propose_work_order]
