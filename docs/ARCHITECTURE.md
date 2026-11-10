# Architecture and design notes

```
OPC UA server (sim) ─► collector ─► parquet ─► dbt (DuckDB: staging → state runs → marts)
                                                    │
                                   detectors (robust-z drift, limits, flatline, IsolationForest)
                                                    │
        FastAPI ◄── ADK SequentialAgent: Detection → Diagnosis (BM25 manuals, citations) → Report (+ work-order proposal)
           │                                         │
     SSE stream ► web UI                  provider switch: Gemini | Azure Foundry | scripted mock | none (replay only)
```

## Design decisions
- **Deterministic first, LLM second.** Statistics find the anomalies; the model explains and prioritizes them. Tools return
  facts, and the report must cite manual sections such as `[MNT-101 §3]`.
- **Human in the loop.** The agents only *propose* work orders (maximum two per run); a person approves them.
- **Known ground truth.** Each scenario has a known injected fault, so detection is testable and the unit tests assert it.
- **Replay-first demo.** Cost stays predictable and the demo keeps working when the model API is unavailable.
- **Cost guards in the application and on the platform.** The documentation states which counters reset on scale-to-zero.
- **Provider-agnostic.** ADK uses Gemini natively and LiteLLM for Azure; a scripted model makes the pipeline testable offline.

## Known limitations
Simulated data and fictional manuals; one line with four machines; no authentication and no persistence of work orders;
the Azure/LiteLLM path needs a first-run check; not a production OT security design.

## Résumé bullets (use only after the demo is live and the claims are verified)
- Built and deployed *Plant Ops Copilot*: multi-agent (Google ADK) anomaly triage for a simulated bottling line, with OPC UA ingestion, dbt/DuckDB models and manual-grounded root-cause analysis with citations.
- Cost-controlled hosting on Azure Container Apps (scale-to-zero, GHCR, usage guards, replay-first demo).
