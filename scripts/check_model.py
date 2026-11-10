"""Smoke test for the model configuration: python -m scripts.check_model

Runs one minimal agent that must call one tool. The check verifies credentials,
endpoint, deployment name and tool calling using a few hundred tokens (well below
$0.001, even on a paid model). Run it before any larger job.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from app.config import Settings  # noqa: E402
from app.llm import build_model, generation_config  # noqa: E402


def ping(x: int) -> dict:
    """Return the number plus one.

    Args:
        x: any integer.
    """
    return {"result": x + 1}


async def main_async() -> int:
    settings = Settings.from_env()
    if settings.provider in ("none", "mock"):
        print(f"LLM_PROVIDER is '{settings.provider}'. Set it to 'gemini' or 'azure' in .env first.")
        return 2
    print(f"Provider: {settings.provider}   Model: {settings.model_label}")

    agent = LlmAgent(
        name="check_agent",
        model=build_model(settings),
        instruction="Call the ping tool with x=41, then reply with exactly: PONG <result>.",
        tools=[ping],
        generate_content_config=generation_config(settings),
    )
    sessions = InMemorySessionService()
    await sessions.create_session(app_name="check", user_id="u", session_id="s")
    runner = Runner(app_name="check", agent=agent, session_service=sessions)
    started = time.monotonic()
    prompt = out = calls = 0
    tool_called, answer = False, ""
    try:
        async for ev in runner.run_async(
            user_id="u", session_id="s",
            new_message=types.Content(role="user", parts=[types.Part(text="go")]),
        ):
            if ev.usage_metadata and not ev.partial:
                prompt += ev.usage_metadata.prompt_token_count or 0
                out += (ev.usage_metadata.candidates_token_count or 0) + (getattr(ev.usage_metadata, "thoughts_token_count", 0) or 0)
                calls += 1
            if ev.get_function_calls():
                tool_called = True
            if ev.is_final_response() and ev.content and ev.content.parts:
                answer = "".join(p.text or "" for p in ev.content.parts)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {str(exc)[:600]}")
        print("Common causes: wrong key/endpoint/deployment name, no quota, model not available in the region.")
        return 1

    cost = settings.estimate_cost(prompt, out)
    print(f"Tool called: {tool_called}   Answer: {answer.strip()!r}")
    print(f"{calls} model calls, {prompt} prompt + {out} output tokens, est. ${cost:.5f}, {time.monotonic() - started:.1f}s")
    if not tool_called:
        print("WARNING: the model did not call the tool. Agents need tool calling; pick another model.")
        return 1
    print("OK: the model works with tool calling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
