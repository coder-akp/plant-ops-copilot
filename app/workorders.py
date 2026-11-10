"""In-memory store for work-order proposals.

No external system is involved. A proposal becomes "approved" only when a person
clicks the approval button in the UI, which mirrors the human-in-the-loop approval
step of a real maintenance workflow.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

MAX_RUNS_KEPT = 200
MAX_ORDERS_PER_RUN = 2
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


@dataclass
class WorkOrder:
    id: str
    run_id: str
    machine_id: str
    priority: str
    title: str
    evidence: str
    suspected_cause: str
    recommended_action: str
    status: str = "pending_approval"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


_lock = threading.Lock()
_store: "OrderedDict[str, dict[str, WorkOrder]]" = OrderedDict()


def normalize_priority(value: str) -> str:
    v = str(value).strip().upper()
    if v.isdigit():
        v = f"P{v}"
    if v not in VALID_PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(VALID_PRIORITIES)}, got {value!r}")
    return v


def propose(run_id: str, machine_id: str, priority: str, title: str, evidence: str,
            suspected_cause: str, recommended_action: str) -> WorkOrder:
    prio = normalize_priority(priority)
    with _lock:
        orders = _store.setdefault(run_id, {})
        if len(orders) >= MAX_ORDERS_PER_RUN:
            raise ValueError(f"at most {MAX_ORDERS_PER_RUN} work orders can be proposed per run")
        wo = WorkOrder(
            id=f"WO-{run_id[:6].upper()}-{len(orders) + 1}",
            run_id=run_id,
            machine_id=machine_id,
            priority=prio,
            title=title[:140],
            evidence=evidence[:600],
            suspected_cause=suspected_cause[:400],
            recommended_action=recommended_action[:600],
        )
        orders[wo.id] = wo
        while len(_store) > MAX_RUNS_KEPT:
            _store.popitem(last=False)
        return wo


def approve(run_id: str, wo_id: str) -> WorkOrder | None:
    with _lock:
        wo = _store.get(run_id, {}).get(wo_id)
        if wo is None:
            return None
        wo.status = "approved"
        return wo


def list_for_run(run_id: str) -> list[WorkOrder]:
    with _lock:
        return list(_store.get(run_id, {}).values())
