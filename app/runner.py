"""Run the agent pipeline and convert ADK events into compact events for the UI.

The same event stream serves live runs (streamed over SSE) and the recordings in
app/replays, which are captured once with the real model and replayed at no cost.

Hard limits protect the budget: a maximum number of tool calls, a token cap per run
and a wall-clock timeout.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents import AGENT_LABELS, build_pipeline
from app.config import Settings
from app.llm import build_model

APP_NAME = "plant_ops_copilot"
MAX_TOOL_CALLS = 12
PREVIEW_CHARS = 1400


def _preview(obj: Any, limit: int = PREVIEW_CHARS) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(obj)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _short_args(args: Any, limit: int = 300) -> dict[str, Any]:
    """Tool-call arguments with long string values shortened for display."""
    out: dict[str, Any] = {}
    for key, value in dict(args or {}).items():
        out[key] = value[: limit - 1] + "…" if isinstance(value, str) and len(value) > limit else value
    return out


def _friendly_error(exc: BaseException) -> str:
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "rate limit" in low or "ratelimit" in low or "resource_exhausted" in low or "quota" in low:
        return "The model provider rate-limited this request (free-tier or quota limit). Please try again in a minute or use the recorded replay."
    if "401" in msg or "403" in msg or "api key" in low or "permission" in low or "authentication" in low:
        return "The model provider rejected the credentials. The owner needs to check the API key configuration."
    if "404" in msg or "deploymentnotfound" in low or "not found" in low:
        return "The configured model or deployment was not found. The owner needs to check the model name."
    return f"The run failed: {type(exc).__name__}: {msg[:240]}"


async def investigate(scenario_id: str, settings: Settings, run_id: str | None = None,
                      meter: dict[str, int] | None = None) -> AsyncIterator[dict[str, Any]]:
    """Run the pipeline for one scenario and yield events as dicts.

    The optional ``meter`` is updated after every model call, so the caller can account
    for the tokens used even if the consumer disconnects mid-run.
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    started = time.monotonic()
    deadline = started + settings.run_timeout_s

    def stamp(ev: dict[str, Any]) -> dict[str, Any]:
        ev["t"] = round(time.monotonic() - started, 2)
        return ev

    yield stamp({"type": "run_start", "run_id": run_id, "scenario": scenario_id,
                 "provider": settings.provider, "model": settings.model_label})

    prompt_tokens = output_tokens = llm_calls = tool_calls = 0
    by_agent: dict[str, dict[str, int]] = {}
    current_agent: str | None = None
    report_text = ""
    failed = False

    def usage_dict() -> dict[str, Any]:
        return {
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "llm_calls": llm_calls,
            "est_cost_usd": round(settings.estimate_cost(prompt_tokens, output_tokens), 5),
            "by_agent": by_agent,
        }

    agen = None
    try:
        model = build_model(settings)
        pipeline = build_pipeline(model, settings)
        sessions = InMemorySessionService()
        await sessions.create_session(
            app_name=APP_NAME, user_id="web", session_id=run_id,
            state={"scenario_id": scenario_id, "run_id": run_id},
        )
        runner = Runner(app_name=APP_NAME, agent=pipeline, session_service=sessions)
        message = types.Content(
            role="user",
            parts=[types.Part(text=f"Investigate the shift data of scenario '{scenario_id}' and produce the handover report.")],
        )
        agen = runner.run_async(user_id="web", session_id=run_id, new_message=message)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"run exceeded {settings.run_timeout_s:.0f}s")
            try:
                event = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                break

            author = event.author
            if author not in AGENT_LABELS:
                continue
            if author != current_agent:
                current_agent = author
                yield stamp({"type": "agent_start", "agent": author, "label": AGENT_LABELS[author]})

            um = event.usage_metadata
            if um is not None and not event.partial:
                p = int(um.prompt_token_count or 0)
                o = int(um.candidates_token_count or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
                prompt_tokens += p
                output_tokens += o
                llm_calls += 1
                if meter is not None:
                    meter["prompt_tokens"], meter["output_tokens"] = prompt_tokens, output_tokens
                agent_usage = by_agent.setdefault(author, {"prompt_tokens": 0, "output_tokens": 0, "llm_calls": 0})
                agent_usage["prompt_tokens"] += p
                agent_usage["output_tokens"] += o
                agent_usage["llm_calls"] += 1

            for call in event.get_function_calls():
                tool_calls += 1
                yield stamp({"type": "tool_call", "agent": author, "name": call.name, "args": _short_args(call.args)})
            for resp in event.get_function_responses():
                body = resp.response if isinstance(resp.response, dict) else {"result": resp.response}
                yield stamp({"type": "tool_result", "agent": author, "name": resp.name, "preview": _preview(body)})
                if resp.name == "propose_work_order" and isinstance(body.get("work_order"), dict):
                    yield stamp({"type": "work_order", "order": body["work_order"]})

            if event.content and event.content.parts and not event.partial:
                text = "".join(p.text for p in event.content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))
                has_tool = bool(event.get_function_calls() or event.get_function_responses())
                if text.strip() and not has_tool:
                    if author == "report_agent":
                        report_text = text.strip()
                    yield stamp({"type": "agent_message", "agent": author, "text": text.strip()})

            if tool_calls > MAX_TOOL_CALLS:
                raise RuntimeError(f"stopped: more than {MAX_TOOL_CALLS} tool calls")
            if prompt_tokens + output_tokens > settings.max_run_tokens:
                raise RuntimeError(f"stopped: token budget of {settings.max_run_tokens} exceeded")
    except BaseException as exc:  # noqa: BLE001 - also catches CancelledError raised on client disconnect
        if isinstance(exc, (asyncio.CancelledError, GeneratorExit)):
            raise
        failed = True
        yield stamp({"type": "error", "message": _friendly_error(exc), "usage": usage_dict()})
    finally:
        if agen is not None:
            try:
                await agen.aclose()
            except Exception:  # noqa: BLE001
                pass

    if not failed:
        yield stamp({"type": "final", "report": report_text, "usage": usage_dict(),
                     "duration_s": round(time.monotonic() - started, 2)})
