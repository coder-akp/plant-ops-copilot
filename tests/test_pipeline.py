"""The full ADK pipeline (agents, tools, state hand-over, streaming) with the scripted model."""
import pytest

from app.config import Settings
from app.runner import investigate


async def run(scenario, language="en", **overrides):
    settings = Settings(provider="mock", **overrides)
    return [ev async for ev in investigate(scenario, settings, language=language)]


def names(events, kind):
    return [e["name"] for e in events if e["type"] == kind]


async def test_bearing_wear_pipeline(db):
    ev = await run("bearing_wear")
    assert [e["agent"] for e in ev if e["type"] == "agent_start"] == ["detection_agent", "diagnosis_agent", "report_agent"]
    assert names(ev, "tool_call") == ["scan_line", "get_signal_trend", "search_manuals", "get_machine_kpis", "propose_work_order"]
    orders = [e for e in ev if e["type"] == "work_order"]
    assert len(orders) == 1 and orders[0]["order"]["machine_id"] == "FILLER-01"
    assert orders[0]["order"]["status"] == "pending_approval"
    final = ev[-1]
    assert final["type"] == "final" and "## Summary" in final["report"]
    assert final["usage"]["llm_calls"] == 8 and final["usage"]["total_tokens"] > 0
    assert all("t" in e for e in ev)


async def test_healthy_shift_creates_no_work_order(db):
    ev = await run("healthy")
    assert not [e for e in ev if e["type"] == "work_order"]
    assert "propose_work_order" not in names(ev, "tool_call")
    assert ev[-1]["type"] == "final"


async def test_tool_arguments_come_from_state_not_the_model(db):
    ev = await run("overheating")
    scan = next(e for e in ev if e["type"] == "tool_call" and e["name"] == "scan_line")
    assert scan["args"] == {}
    result = next(e for e in ev if e["type"] == "tool_result" and e["name"] == "scan_line")
    assert "CAPPER-01" in result["preview"]


async def test_token_budget_stops_the_run(db):
    ev = await run("bearing_wear", max_run_tokens=500)
    assert ev[-1]["type"] == "error"
    assert "budget" in ev[-1]["message"].lower()
    assert not any(e["type"] == "final" for e in ev)


async def test_misconfigured_azure_gives_a_clear_error(db):
    ev = await run_provider("azure")
    assert ev[-1]["type"] == "error"
    assert "AZURE_OPENAI" in ev[-1]["message"] or "failed" in ev[-1]["message"]


async def run_provider(provider):
    settings = Settings(provider=provider)
    return [e async for e in investigate("healthy", settings)]


async def test_german_run_writes_german_output_and_keeps_machine_data(db):
    ev = await run("bearing_wear", language="de")
    assert ev[0]["language"] == "de"
    final = ev[-1]
    assert final["type"] == "final" and "## Zusammenfassung" in final["report"] and "## Summary" not in final["report"]
    order = next(e for e in ev if e["type"] == "work_order")["order"]
    assert order["machine_id"] == "FILLER-01" and "prüfen" in order["title"]
    assert names(ev, "tool_call") == ["scan_line", "get_signal_trend", "search_manuals", "get_machine_kpis", "propose_work_order"]


async def test_german_healthy_shift_creates_no_work_order(db):
    ev = await run("healthy", language="de")
    assert not [e for e in ev if e["type"] == "work_order"]
    assert "Keine Diagnose erforderlich" in next(e for e in ev if e["type"] == "agent_message" and e["agent"] == "diagnosis_agent")["text"]


def test_language_is_part_of_the_agent_instructions():
    from app.agents import DETECTION_INSTRUCTION, DIAGNOSIS_INSTRUCTION, REPORT_INSTRUCTION, localize_instruction

    assert localize_instruction("detection", DETECTION_INSTRUCTION, "en") == DETECTION_INSTRUCTION
    de_diag = localize_instruction("diagnosis", DIAGNOSIS_INSTRUCTION, "de")
    assert "German (de)" in de_diag and "search_manuals query in English" in de_diag and "{detection_findings?}" in de_diag
    de_rep = localize_instruction("report", REPORT_INSTRUCTION, "de")
    assert "## Zusammenfassung" in de_rep and "title, evidence, suspected_cause" in de_rep
    with pytest.raises(ValueError):
        localize_instruction("report", REPORT_INSTRUCTION, "fr")
