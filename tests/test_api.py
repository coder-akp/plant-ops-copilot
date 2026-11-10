import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.server import create_app


@pytest.fixture()
def client(db, tmp_path):
    (tmp_path / "healthy.json").write_text(json.dumps({"meta": {"model": "test"}, "events": [{"type": "final", "t": 0}]}))
    settings = Settings(db_path=db, provider="mock", replay_dir=tmp_path, cooldown_s=0)
    with TestClient(create_app(settings)) as c:
        yield c


def sse(response):
    return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def test_static_page_and_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "Plant Ops Copilot" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/docs").status_code == 404


def test_status_scenarios_overview(client):
    st = client.get("/api/status").json()
    assert st["provider"] == "mock" and st["live_available"] is True
    scenarios = client.get("/api/scenarios").json()
    assert [s["id"] for s in scenarios] == ["healthy", "bearing_wear", "overheating", "sensor_fault"]
    assert scenarios[0]["has_replay"] is True and scenarios[1]["has_replay"] is False
    ov = client.get("/api/scenarios/overheating/overview").json()
    assert ov["scan"]["findings"][0]["machine_id"] == "CAPPER-01" and len(ov["kpis"]) == 4


def test_series_endpoint_and_validation(client):
    r = client.get("/api/scenarios/bearing_wear/series", params={"machine": "FILLER-01", "signal": "vibration_mm_s"}).json()
    assert len(r["points"]) == 360 and r["windows"] and r["limits"]["alert"] == 4.5
    assert client.get("/api/scenarios/nope/overview").status_code == 404
    assert client.get("/api/scenarios/..%2Fetc/overview").status_code == 404
    assert client.get("/api/scenarios/healthy/series", params={"machine": "X", "signal": "temp_c"}).status_code == 400


def test_replay_endpoint(client):
    assert client.get("/api/replay/healthy").json()["meta"]["model"] == "test"
    assert client.get("/api/replay/bearing_wear").status_code == 404


def test_live_run_streams_events_and_approval(client):
    with client.stream("POST", "/api/investigate", json={"scenario": "bearing_wear"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = sse(r)
    assert events[0]["type"] == "run_start" and events[-1]["type"] == "final"
    wo = next(e for e in events if e["type"] == "work_order")["order"]
    ok = client.post("/api/approve", json={"run_id": wo["run_id"], "order_id": wo["id"]}).json()
    assert ok["status"] == "approved" and ok["simulated"] is False
    sim = client.post("/api/approve", json={"run_id": "replay", "order_id": "x"}).json()
    assert sim["simulated"] is True


def test_live_run_is_rate_limited_per_visitor(db, tmp_path):
    settings = Settings(db_path=db, provider="mock", replay_dir=tmp_path, cooldown_s=0, per_ip_max_runs=1)
    with TestClient(create_app(settings)) as c:
        with c.stream("POST", "/api/investigate", json={"scenario": "healthy"}) as r:
            assert r.status_code == 200
            sse(r)
        denied = c.post("/api/investigate", json={"scenario": "healthy"})
        assert denied.status_code == 429 and "limit" in denied.json()["detail"]
        assert c.get("/api/status").json()["runs_left_today"] == settings.daily_max_runs - 1


def test_live_disabled_and_access_code(db, tmp_path):
    off = Settings(db_path=db, provider="none", replay_dir=tmp_path)
    with TestClient(create_app(off)) as c:
        assert c.get("/api/status").json()["live_available"] is False
        assert c.post("/api/investigate", json={"scenario": "healthy"}).status_code == 503
    locked = Settings(db_path=db, provider="mock", replay_dir=tmp_path, access_code="sesame", cooldown_s=0)
    with TestClient(create_app(locked)) as c:
        assert c.post("/api/investigate", json={"scenario": "healthy"}).status_code == 403
        with c.stream("POST", "/api/investigate", json={"scenario": "healthy", "code": "sesame"}) as r:
            assert r.status_code == 200
            sse(r)


def test_bad_input_is_rejected(client):
    assert client.post("/api/investigate", json={"scenario": "../../etc"}).status_code == 404
    assert client.post("/api/investigate", json={}).status_code == 422
    assert client.post("/api/investigate", json={"scenario": "x" * 500}).status_code == 422
