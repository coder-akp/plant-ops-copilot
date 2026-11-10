"""FastAPI application: JSON API, server-sent events and the static web UI."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import data, detect, workorders
from app.config import Settings
from app.guard import UsageGuard
from app.runner import investigate
from app.tools import clear_caches, scan_for_scenario
from sim.line import MACHINES, SCENARIOS

STATIC_DIR = Path(__file__).resolve().parent / "static"
VERSION = "1.0.0"
_SAFE_ID = re.compile(r"^[a-z0-9_\-]{1,40}$")


class InvestigateBody(BaseModel):
    scenario: str = Field(max_length=40)
    code: str | None = Field(default=None, max_length=100)


class ApproveBody(BaseModel):
    run_id: str = Field(max_length=40)
    order_id: str = Field(max_length=40)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not Path(settings.db_path).is_file():
        raise FileNotFoundError(
            f"Database not found at {settings.db_path}. Build it first with: python -m scripts.build_data "
            "(generates the simulator data and runs the dbt models)."
        )
    data.configure(settings.db_path)
    clear_caches()
    guard = UsageGuard(settings)
    scenarios_present = data.available_scenarios()

    def warm_caches() -> None:
        # Without warm-up, the first request per scenario pays about 0.6 s for the detectors
        for sid in scenarios_present:
            try:
                scan_for_scenario(sid)
                scan_for_scenario(sid, include_windows=True)
            except Exception:  # noqa: BLE001 - warm-up is best effort
                pass

    threading.Thread(target=warm_caches, daemon=True, name="warm-caches").start()

    app = FastAPI(title="Plant Ops Copilot", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return response

    def check_scenario(sid: str) -> str:
        if not _SAFE_ID.match(sid) or sid not in scenarios_present:
            raise HTTPException(404, "unknown scenario")
        return sid

    def replay_path(sid: str) -> Path:
        return settings.replay_dir / f"{sid}.json"

    # Pages
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True, "version": VERSION}

    # API
    @app.get("/api/status")
    def status() -> dict:
        g = guard.status()
        live_possible = settings.provider != "none" and settings.live_enabled
        return {
            "version": VERSION,
            "provider": settings.provider,
            "model": settings.model_label,
            "live_available": live_possible,
            "live_requires_code": bool(settings.access_code),
            "runs_left_today": g["runs_left_today"] if live_possible else 0,
            "busy": g["busy"],
            "github_url": settings.github_url,
            "price_note": (
                "free tier" if settings.provider == "gemini"
                else f"estimated at ${settings.price_in_per_m:g} / ${settings.price_out_per_m:g} per 1M tokens (in / out)"
                if settings.provider == "azure" else ""
            ),
        }

    @app.get("/api/scenarios")
    def scenarios() -> list[dict]:
        out = []
        for sid in scenarios_present:
            meta = SCENARIOS.get(sid)
            out.append({
                "id": sid,
                "title": meta.title if meta else sid,
                "story": meta.story if meta else "",
                "ground_truth": meta.ground_truth if meta else "",
                "has_replay": replay_path(sid).is_file(),
            })
        return out

    @app.get("/api/scenarios/{sid}/overview")
    def overview(sid: str) -> dict:
        check_scenario(sid)
        return {"kpis": data.machine_kpis(sid), "scan": scan_for_scenario(sid)}

    @app.get("/api/scenarios/{sid}/series")
    def series(sid: str, machine: str, signal: str) -> dict:
        check_scenario(sid)
        if machine not in MACHINES or signal not in detect.SIGNALS:
            raise HTTPException(400, "unknown machine or signal")
        payload = detect.chart_series(data.scenario_frame(sid), machine, signal)
        windows = []
        for f in scan_for_scenario(sid, include_windows=True)["findings"]:
            if f["machine_id"] == machine and f["signal"] == signal:
                windows.extend(f.get("windows", []))
        payload["windows"] = windows
        payload["stops"] = [
            {"state": r["state"], "start": r["start"], "end": r["end"]}
            for r in data.state_runs(sid, machine, min_duration_s=60)
        ]
        return payload

    @app.get("/api/replay/{sid}")
    def replay(sid: str) -> JSONResponse:
        check_scenario(sid)
        path = replay_path(sid)
        if not path.is_file():
            raise HTTPException(404, "no recorded run for this scenario")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.post("/api/investigate")
    async def investigate_endpoint(body: InvestigateBody, request: Request):
        sid = check_scenario(body.scenario)
        decision = guard.acquire(client_ip(request), body.code)
        if not decision.allowed:
            return JSONResponse({"detail": decision.reason}, status_code=decision.status)

        async def stream():
            meter: dict[str, int] = {"prompt_tokens": 0, "output_tokens": 0}
            try:
                async for event in investigate(sid, settings, meter=meter):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                guard.release(settings.estimate_cost(meter["prompt_tokens"], meter["output_tokens"]))

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/approve")
    def approve(body: ApproveBody) -> dict:
        wo = workorders.approve(body.run_id, body.order_id)
        if wo is None:  # recorded replays: nothing is stored on the server, so the UI simulates the approval
            return {"status": "approved", "simulated": True, "order_id": body.order_id}
        return {"status": wo.status, "simulated": False, "order_id": wo.id}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app

