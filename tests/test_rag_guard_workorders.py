import pytest

from app import rag, workorders
from app.config import Settings
from app.guard import UsageGuard


@pytest.mark.parametrize("query,expected", [
    ("bearing wear vibration drift limits", "MNT-101"),
    ("capper cooling fan failure thermal trip", "MNT-102"),
    ("stuck temperature sensor flatline dropout", "MNT-103"),
    ("priority P1 P2 response time", "MNT-105"),
])
def test_retrieval_finds_the_right_manual(query, expected):
    hits = rag.search(query, top_k=3)
    assert hits and hits[0]["source"].startswith(expected)
    assert "§" in hits[0]["source"]


def test_retrieval_with_no_match_is_empty():
    assert rag.search("quantum chromodynamics lattice", top_k=3) == []


def make_guard(**kw):
    now = [1_000_000.0]
    s = Settings(provider="mock", cooldown_s=10, daily_max_runs=3, per_ip_max_runs=2, daily_budget_usd=0.05, **kw)
    return UsageGuard(s, clock=lambda: now[0]), now


def test_guard_blocks_when_not_configured_or_disabled():
    assert UsageGuard(Settings(provider="none")).acquire("ip", None).status == 503
    assert UsageGuard(Settings(provider="mock", live_enabled=False)).acquire("ip", None).status == 503


def test_guard_access_code():
    g, _ = make_guard(access_code="sesame")
    assert g.acquire("ip", None).status == 403
    assert g.acquire("ip", "wrong").status == 403
    assert g.acquire("ip", "sesame").allowed


def test_guard_cooldown_concurrency_and_caps():
    g, now = make_guard()
    assert g.acquire("a", None).allowed
    assert g.acquire("b", None).status == 429          # busy
    g.release(0.0)
    assert g.acquire("b", None).status == 429          # cooldown
    now[0] += 11
    assert g.acquire("a", None).allowed                # second run for visitor a
    g.release(0.0)
    now[0] += 11
    assert g.acquire("a", None).status == 429          # per-visitor cap
    assert g.acquire("b", None).allowed                # third run overall
    g.release(0.0)
    now[0] += 11
    assert g.acquire("c", None).status == 429          # daily cap


def test_guard_budget_and_day_rollover():
    g, now = make_guard()
    assert g.acquire("a", None).allowed
    g.release(0.06)                                    # spend exceeds the 0.05 budget
    now[0] += 11
    assert "budget" in g.acquire("b", None).reason
    now[0] += 86_400
    assert g.acquire("b", None).allowed                # new UTC day: counters reset
    assert g.status()["runs_today"] == 1


def test_workorder_flow():
    wo = workorders.propose("run1234567", "FILLER-01", "2", "t", "e", "c", "a")
    assert wo.priority == "P2" and wo.status == "pending_approval"
    workorders.propose("run1234567", "FILLER-01", "P3", "t", "e", "c", "a")
    with pytest.raises(ValueError):
        workorders.propose("run1234567", "FILLER-01", "P1", "t", "e", "c", "a")  # limit of two per run
    with pytest.raises(ValueError):
        workorders.normalize_priority("urgent")
    assert workorders.approve("run1234567", wo.id).status == "approved"
    assert workorders.approve("run1234567", "nope") is None


def test_machine_scoped_search_never_returns_other_machines_manuals():
    hits = rag.search("temperature rises exponentially trip thermal protection cooling", machine_id="CAPPER-01")
    assert hits and hits[0]["source"].startswith("MNT-102")
    assert all(not h["source"].startswith("MNT-101") for h in hits)
    filler = rag.search("lubrication friction temperature", machine_id="FILLER-01")
    assert all(not h["source"].startswith("MNT-102") for h in filler)
