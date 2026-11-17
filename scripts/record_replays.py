"""Record one live run per scenario with the configured model.

    python -m scripts.record_replays                       # all scenarios, English and German
    python -m scripts.record_replays bearing_wear          # selected scenarios
    python -m scripts.record_replays --lang de             # German only
    python -m scripts.record_replays --pause 25            # wait 25 s between runs (free-tier rate limits)

Recordings are written to app/replays/<scenario>.json (English) and
app/replays/<scenario>.de.json (German). The agents are instructed in the target
language from the start, so each recording is genuine model output in that language.
The deployed demo plays them back at no cost, so most visitors never trigger a paid
model call. The script prints the token counts and the estimated cost of the session.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import data  # noqa: E402
from app.agents import LANGUAGES  # noqa: E402
from app.config import Settings  # noqa: E402
from app.runner import investigate  # noqa: E402
from app.tools import clear_caches  # noqa: E402
from sim.line import SCENARIOS  # noqa: E402


async def record(scenario: str, settings: Settings, language: str) -> tuple[dict, list[dict]] | None:
    events: list[dict] = []
    async for ev in investigate(scenario, settings, language=language):
        events.append(ev)
        if ev["type"] == "agent_start":
            print(f"   {ev['label']} ...")
        if ev["type"] == "error":
            print(f"   ERROR: {ev['message']}")
            return None
    final = events[-1]
    meta = {
        "scenario": scenario,
        "provider": settings.provider,
        "model": settings.model_label,
        "language": language,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "usage": final["usage"],
    }
    return meta, events


async def main_async(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    if settings.provider == "none":
        print("LLM_PROVIDER is 'none'. Configure a provider in .env first (see .env.example).")
        return 2
    if settings.provider == "mock" and not args.allow_mock:
        print("Refusing to record scripted (mock) output as a replay. Use --allow-mock only for testing.")
        return 2

    data.configure(settings.db_path)
    clear_caches()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    wanted = args.scenarios or list(SCENARIOS)
    languages = list(LANGUAGES) if args.lang == "all" else [args.lang]
    total_tokens, total_cost, failures, first = 0, 0.0, 0, True
    for language in languages:
        for sid in wanted:
            if not first and args.pause:
                await asyncio.sleep(args.pause)
            first = False
            print(f"== {sid} [{language}] ({settings.model_label})")
            result = await record(sid, settings, language)
            if result is None:
                failures += 1
                continue
            meta, events = result
            name = f"{sid}.json" if language == "en" else f"{sid}.{language}.json"
            (out / name).write_text(json.dumps({"meta": meta, "events": events}, ensure_ascii=False, indent=1), encoding="utf-8")
            u = meta["usage"]
            total_tokens += u["total_tokens"]
            total_cost += u["est_cost_usd"]
            print(f"   saved {name}. {u['llm_calls']} model calls, {u['total_tokens']:,} tokens, est. ${u['est_cost_usd']:.4f}")
    print(f"\nTotal: {total_tokens:,} tokens, estimated ${total_cost:.4f}. Failures: {failures}")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenarios", nargs="*", help="scenario ids (default: all)")
    parser.add_argument("--out", default=str(ROOT / "app" / "replays"))
    parser.add_argument("--lang", choices=[*LANGUAGES, "all"], default="all", help="output language of the agents (default: all)")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds to wait between runs, for free-tier rate limits")
    parser.add_argument("--allow-mock", action="store_true", help="testing only")
    args = parser.parse_args()
    unknown = [s for s in args.scenarios if s not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario(s): {unknown}; choose from {list(SCENARIOS)}")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
