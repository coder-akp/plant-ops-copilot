"""Scripted, deterministic stand-in for an LLM.

This is not a language model. It allows the complete ADK pipeline (agent hand-over,
tool calling, state passing, event streaming and the web UI) to run in tests and in
offline development without an API key or any cost. The next tool call is chosen
from the agent instruction and from the tool results already present in the
conversation, and the answer is composed from those results.

All output carries the prefix "[scripted]" so that it cannot be mistaken for real
model output.
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

TAG = "[scripted] "
_FINDING_RE = re.compile(r"- ((?:FILLER|CAPPER|LABELER|PACKER)-01) (\w+)")


def _first_finding(text: str) -> tuple[str, str]:
    """Return (machine, signal) for the first finding line in the detection summary."""
    m = _FINDING_RE.search(text)
    if m:
        return m.group(1), m.group(2)
    machine = re.search(r"(?:FILLER|CAPPER|LABELER|PACKER)-01", text)
    return (machine.group(0) if machine else "FILLER-01"), ""


def _instruction_text(req: LlmRequest) -> str:
    si = req.config.system_instruction if req.config else None
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    parts = getattr(si, "parts", None) or []
    return "\n".join(p.text for p in parts if getattr(p, "text", None))


def _function_responses(req: LlmRequest) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for content in req.contents or []:
        for part in content.parts or []:
            fr = getattr(part, "function_response", None)
            if fr is not None:
                out[fr.name] = fr.response
    return out


def _call(name: str, args: dict[str, Any]) -> LlmResponse:
    part = types.Part(function_call=types.FunctionCall(name=name, args=args))
    return LlmResponse(content=types.Content(role="model", parts=[part]))


def _text(text: str) -> LlmResponse:
    sep = "\n\n" if text.startswith("##") else ""  # keep Markdown headings at the start of a line
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=TAG.strip() + (sep or " ") + text)]))


def _with_usage(resp: LlmResponse, req: LlmRequest) -> LlmResponse:
    prompt_chars = len(_instruction_text(req)) + sum(len(str(c)) for c in (req.contents or []))
    out_chars = len(str(resp.content))
    prompt_t, out_t = prompt_chars // 4, max(out_chars // 4, 1)
    resp.usage_metadata = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt_t, candidates_token_count=out_t, total_token_count=prompt_t + out_t
    )
    return resp


class ScriptedLlm(BaseLlm):
    model: str = "scripted-v1"

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        text = _instruction_text(llm_request)
        done = _function_responses(llm_request)
        if "Detection Agent" in text:
            resp = self._detection(done)
        elif "Diagnosis Agent" in text:
            resp = self._diagnosis(text, done)
        elif "Report Agent" in text:
            resp = self._report(text, done)
        else:
            resp = _text("Hello from the scripted model.")
        yield _with_usage(resp, llm_request)

    @staticmethod
    def _detection(done: dict[str, Any]) -> LlmResponse:
        scan = done.get("scan_line")
        if scan is None:
            return _call("scan_line", {})
        findings = scan.get("findings", [])
        if not findings:
            return _text("No anomalies detected. The line looks healthy: all machines stay within their baseline and alarm limits.")
        top = findings[0]
        if "get_signal_trend" not in done:
            return _call("get_signal_trend", {"machine_id": top["machine_id"], "signal": top["signal"]})
        lines = []
        for f in findings[:2]:
            ev = f["evidence"]
            bits = [f"{k}={v}" for k, v in ev.items() if k in {
                "first_breach", "first_alert_breach", "first_trip_level", "flatline_minutes", "flatline_from", "flatline_to",
                "missing_minutes", "dropout_from", "dropout_to", "baseline", "latest", "max", "alert_limit", "trip_limit",
                "hours_to_alert_at_current_trend"}]
            lines.append(f"- {f['machine_id']} {f['signal']} (severity {f['severity']}): {', '.join(f['issues'])}; " + ", ".join(bits))
        return _text("Findings:\n" + "\n".join(lines))

    @staticmethod
    def _diagnosis(instruction: str, done: dict[str, Any]) -> LlmResponse:
        low = instruction.lower()
        if "no anomalies detected" in low or "looks healthy" in low:
            return _text("No diagnosis needed.")
        machine, signal = _first_finding(instruction)
        if "search_manuals" not in done:
            if "stuck_sensor" in low or "signal_dropout" in low:
                query = "stuck temperature sensor flatline dropout diagnostics"
            elif signal == "temp_c":
                query = "capper cooling fan failure thermal trip"
            else:
                query = "bearing wear vibration drift limits"
            return _call("search_manuals", {"query": query})
        if "get_machine_kpis" not in done:
            return _call("get_machine_kpis", {"machine_id": machine})
        results = done["search_manuals"].get("results", [])
        cites = ", ".join(f"[{r['source']}]" for r in results[:2]) or "[no source]"
        kpi = done["get_machine_kpis"]
        return _text(
            f"Most likely cause for {machine}: see {cites}. "
            f"Availability {kpi.get('availability_pct')} %, {kpi.get('fault_events')} fault events. Confidence: medium."
        )

    @staticmethod
    def _report(instruction: str, done: dict[str, Any]) -> LlmResponse:
        low = instruction.lower()
        healthy = "no anomalies detected" in low or "looks healthy" in low
        if healthy:
            return _text("## Summary\nNo action required. All machines are within limits.\n\n## Findings\n| Machine | Issue | Priority | Confidence |\n|---|---|---|---|\n| none | none | P4 | high |\n\n## Recommended actions\n1. Continue normal operation.\n\n## Notes\nScripted output for offline testing.")
        machine, _ = _first_finding(instruction)
        if "propose_work_order" not in done:
            return _call("propose_work_order", {
                "machine_id": machine,
                "priority": "P2",
                "title": f"Inspect {machine}",
                "evidence": "See detection findings above.",
                "suspected_cause": "See diagnosis above.",
                "recommended_action": "Inspect at next planned stop.",
            })
        wo = done["propose_work_order"].get("work_order", {})
        return _text(
            f"## Summary\nAn anomaly was found on {machine}. A work order was proposed and awaits approval.\n\n"
            f"## Findings\n| Machine | Issue | Priority | Confidence |\n|---|---|---|---|\n| {machine} | see detection | {wo.get('priority', 'P2')} | medium |\n\n"
            f"## Recommended actions\n1. Approve work order {wo.get('id', '')} and inspect {machine}.\n\n"
            "## Notes\nScripted output for offline testing; not real model output."
        )
