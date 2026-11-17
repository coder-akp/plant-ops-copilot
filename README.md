# Plant Ops Copilot

Live demo of agentic AI for manufacturing operations. A simulated bottling line streams sensor data over OPC UA,
dbt models the data in DuckDB, statistical detectors flag anomalies, and a three-agent pipeline (Google ADK)
investigates the findings, cites the maintenance manuals and **proposes** a work order that a person approves.

**Live demo:** [plantops.abhaydev.live](https://plantops.abhaydev.live) · **Source:** [coder-akp/plant-ops-copilot](https://github.com/coder-akp/plant-ops-copilot)

The first visit after an idle period takes a few seconds while the container starts from zero.

![Scenario selection and detector findings](docs/img/01-overview.png)

## Usage
Select a scenario (healthy, bearing wear, overheating, sensor fault), then choose **Replay** (free, instant)
or **Run live** (real model call, rate-limited). The interface offers English and German, light and dark themes,
a 3D view of the line with a 2D fallback, a guided tour and a presentation mode.

The language applies to the agents as well: the language is part of the agent instructions, so the agents write
their findings, the report and the work-order text in the selected language from the start. Nothing is translated
afterwards. Recorded replays exist per language (`app/replays/<scenario>.json` and `<scenario>.de.json`); a missing
German recording falls back to the English one with a visible notice.

## Screenshots
| Line data (computed live, no LLM) | Agent trace (tool calls, citations) |
|---|---|
| ![Line data](docs/img/02-line-data.png) | ![Agent trace](docs/img/03-agent-trace.png) |

| Report and proposed work order | Mobile |
|---|---|
| ![Report and work order](docs/img/04-report-and-work-order.png) | <img src="docs/img/05-mobile.png" width="260" alt="Mobile view"> |

## Front end
Plain JavaScript and CSS without a framework. The 3D scene (`app/static/scene.js`, about 130 KB compressed) loads after
the page is usable and is built from `frontend/scene.src.js` with `npm run build` in `frontend/`. Strings live in
`app/static/i18n.js`. The browser check `python -m scripts.e2e_ui <url>` covers both languages, both themes, desktop and mobile.

## Run locally
```bash
pip install -r requirements-dev.txt
python -m scripts.build_data
LLM_PROVIDER=mock uvicorn app.server:create_app --factory   # scripted model, no API key
python -m pytest -q
```
Complete setup including deployment: [docs/START_HERE.md](docs/START_HERE.md) · design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · cost: [docs/COSTS.md](docs/COSTS.md)

## Limitations
The data is simulated, the manuals are fictional and the security model is demo-grade. LLM output can be wrong,
which is why work orders require human approval.

Built by [Abhay Kumar Patel](https://github.com/coder-akp). MIT licensed.
