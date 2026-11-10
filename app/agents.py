"""Multi-agent pipeline built on Google ADK.

    plant_ops_copilot (SequentialAgent)
      1. detection_agent  -> finds and quantifies anomalies           (tools: scan_line, get_signal_trend)
      2. diagnosis_agent  -> root-cause hypotheses with citations     (tools: search_manuals, get_machine_kpis)
      3. report_agent     -> handover report and work-order proposals (tool: propose_work_order)

Agents pass state to each other through the ADK session state (output_key), so each
later agent receives a short summary instead of the full transcript. This keeps
token usage low.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent

from app.config import Settings
from app.llm import generation_config
from app.tools import DETECTION_TOOLS, DIAGNOSIS_TOOLS, REPORT_TOOLS

AGENT_LABELS = {
    "detection_agent": "Detection agent",
    "diagnosis_agent": "Diagnosis agent",
    "report_agent": "Report agent",
}

DETECTION_INSTRUCTION = """You are the Detection Agent of a plant operations copilot for a bottling line with the machines FILLER-01, CAPPER-01, LABELER-01 and PACKER-01.

Goal: find out which machines behave abnormally in the current shift data.

Procedure:
1. Call scan_line exactly once.
2. For the most severe finding, and at most one finding on a different machine or signal, call get_signal_trend once to see how it developed over the shift.
3. Reply with a concise summary of at most 150 words. For each finding give: machine, signal, what is abnormal (use the numbers and clock times from the tools), the alarm limits, and the trend or time-to-limit if available.

Rules:
- Use only numbers returned by the tools. Never invent values.
- If scan_line returns no findings, say plainly that the line looks healthy and no anomalies were detected. Do not invent problems.
- Finding types: drift = slow change versus baseline; stuck_sensor = value frozen while the machine runs; signal_dropout = missing data; alert_limit_breach and trip_limit_reached = alarm limits."""

DIAGNOSIS_INSTRUCTION = """You are the Diagnosis Agent of a plant operations copilot.

Detection findings from the previous agent:
{detection_findings?}

Task: explain the most likely root cause of each finding using the maintenance knowledge base.

Procedure:
- If the findings say the line is healthy, reply exactly: No diagnosis needed.
- Otherwise call search_manuals with a short, focused query per distinct finding (at most 3 calls in total). Always pass machine_id. Describe the SYMPTOM you observed (signal, direction, limits, trips, repeating pattern) and do not put a guessed cause into the query; the manuals list the failure signatures.
- Call get_machine_kpis once for the most affected machine to check availability and stops.

Rules:
- Cite sources exactly as returned, for example [MNT-101 §3]. Compare the observed pattern with the failure signature in the manual (rise shape, time constant, trip cycle, other signals) and say whether it matches. Only claim a cause that a returned passage supports.
- Distinguish real machine degradation from instrumentation faults: a stuck or missing sensor signal while related signals such as motor current and vibration stay normal points to the sensor, not the machine.
- Output at most 180 words. For each finding: most likely cause, one alternative, evidence for and against, confidence (low, medium or high)."""

REPORT_INSTRUCTION = """You are the Report Agent of a plant operations copilot. You write the shift handover report.

Detection findings:
{detection_findings?}

Diagnosis:
{diagnosis?}

Write the report in Markdown with exactly these sections:
## Summary
Two sentences.
## Findings
A table with the columns Machine, Issue, Priority, Confidence.
## Recommended actions
A numbered list.
## Notes
One or two sentences on limitations or follow-up checks.

Priorities follow the matrix in MNT-105: P1 = trip limit reached or two or more protective trips within one hour, P2 = alert limit breached or predicted to be breached within 4 hours, P3 = drift without limit breach or instrumentation fault, P4 = informational.

For every finding that needs maintenance action (P1 to P3) call propose_work_order once, at most 2 calls in total and at most ONE per machine (combine related findings on the same machine into one order), before you write the report. Work orders are only proposals that a human must approve: never state that an action was carried out.
If the line is healthy, write a short report saying no action is required and do not create any work order.
Use only facts from the findings and diagnosis above."""


def build_pipeline(model, settings: Settings) -> SequentialAgent:
    """Build a new agent tree. A separate tree is created for each run."""
    config = generation_config(settings)

    detection = LlmAgent(
        name="detection_agent",
        model=model,
        description="Finds and quantifies anomalies in the shift data.",
        instruction=DETECTION_INSTRUCTION,
        tools=DETECTION_TOOLS,
        output_key="detection_findings",
        generate_content_config=config,
    )
    diagnosis = LlmAgent(
        name="diagnosis_agent",
        model=model,
        description="Explains likely root causes using the maintenance manuals.",
        instruction=DIAGNOSIS_INSTRUCTION,
        tools=DIAGNOSIS_TOOLS,
        output_key="diagnosis",
        include_contents="none",
        generate_content_config=config,
    )
    report = LlmAgent(
        name="report_agent",
        model=model,
        description="Writes the handover report and proposes work orders.",
        instruction=REPORT_INSTRUCTION,
        tools=REPORT_TOOLS,
        output_key="shift_report",
        include_contents="none",
        generate_content_config=config,
    )
    return SequentialAgent(
        name="plant_ops_copilot",
        description="Detects, diagnoses and reports anomalies on a bottling line.",
        sub_agents=[detection, diagnosis, report],
    )
