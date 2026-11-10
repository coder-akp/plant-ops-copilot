# Setup guide: from project archive to a live link

Legend: **[MANUAL]** marks a step that requires an account, a key or a portal action. **[INCLUDED]** marks work that is already part of the project.

## Included in the project [INCLUDED]
Simulator with OPC UA server and collector, dbt models (DuckDB), detectors (drift, alarm limits, flatline and dropout,
Isolation Forest), manual search with citations, three Google ADK agents (Detection → Diagnosis → Report),
work-order proposals that need human approval, web UI, cost guards, automated tests, Dockerfile, CI workflow and
Azure deployment scripts.

## Steps

### 1. Run locally (about 15 minutes, free) [MANUAL]
Requires Python 3.13 and Git. From the project folder:
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell; macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m scripts.build_data      # simulates data and runs dbt -> data/plantops.duckdb
python -m pytest -q               # all tests should pass
copy .env.example .env            # macOS/Linux: cp .env.example .env
```
In `.env`, set `LLM_PROVIDER=mock`, then start the server:
```bash
uvicorn app.server:create_app --factory --port 8000
```
Open http://localhost:8000. In this mode, "Run live" uses a **scripted stand-in model**, so every control can be tested at no cost.
Mock output must never be published as a demo; the recorder refuses to save it.

### 2. Choose the model route [MANUAL]
**Route A: Gemini free tier (recommended; keeps the full $100 credit).**
1. Open https://aistudio.google.com, choose "Get API key" and create a key.
2. In `.env`, set `LLM_PROVIDER=gemini`, `GOOGLE_API_KEY=...` and `GEMINI_MODEL=` to a model that AI Studio lists as free tier.
   Current free-tier limits and model names are not verified here; check the AI Studio rate-limit page.
3. Run `python -m scripts.check_model`. It must print a success line.
   On the free tier, Google may use prompts to improve its products. The data in this project is fictional, so this is acceptable.

**Route B: Azure Foundry (uses credits; only if the subscription allows it).**
1. Run `az login`, then `python -m scripts.azure_preflight`. Apart from registering the Microsoft.App resource provider,
   the script only reads subscription data. It reports the allowed regions, Container Apps availability and
   whether model quota exists. If no quota is reported, use Route A.
2. In https://ai.azure.com, create a project in a region from the preflight output, open Models + endpoints and deploy
   a small model (for example a "mini" model). Set the **lowest tokens-per-minute** capacity, which acts as a hard spending limit.
3. In `.env`, set `LLM_PROVIDER=azure`, `AZURE_OPENAI_ENDPOINT` (the `https://….openai.azure.com/` URL),
   `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_DEPLOYMENT` (the deployment name). Set `AZURE_REASONING_EFFORT=low` only for
   gpt-5-family models, and take `PRICE_IN_PER_M` / `PRICE_OUT_PER_M` from the Azure pricing page for the chosen model.
   Compare `AZURE_OPENAI_API_VERSION` with the version shown in the portal for the deployment.
4. Run `python -m scripts.check_model`. This Azure path has not been tested against a real Azure account, so one round of adjustment may be needed.

### 3. Record the replays (small cost, free on the Gemini tier) [MANUAL]
```bash
python -m scripts.record_replays
```
Review each `app/replays/*.json` recording in the UI (start `uvicorn …` and select Replay). Re-record a scenario if its report is poor.
Visitors receive these recordings instantly and at no cost; live runs are optional.

### 4. Publish on GitHub [MANUAL]
Create a **public** repository named `plant-ops-copilot`, then run:
```bash
git init && git add . && git commit -m "Plant Ops Copilot" && git branch -M main
git remote add origin https://github.com/<github-user>/plant-ops-copilot.git && git push -u origin main
```
Confirm that `git status` does not list `.env` (it is git-ignored). The Actions tab then runs the tests and publishes the image to
`ghcr.io/<github-user>/plant-ops-copilot`. When the workflow is green, open GitHub profile → Packages → the package →
Package settings → Change visibility → **Public**. Otherwise Azure cannot pull the image without a token.

### 5. Deploy on Azure (about 10 minutes) [MANUAL]
Requires the Azure CLI. On Windows, run the `.sh` files in Git Bash, WSL or Azure Cloud Shell.
Add `LOCATION=<region from preflight>` and `IMAGE=ghcr.io/<github-user, lower case>/plant-ops-copilot:latest` to `.env`, then run:
```bash
az login
bash infra/deploy.sh
```
The script prints the site URL. Add it to the résumé, LinkedIn and the GitHub repository description.
After pushing new code, wait for the Action to finish and run `bash infra/deploy.sh` again.

### 6. Safeguards [MANUAL]
- Azure portal → Cost Management → Budgets: add a budget (for example $10) with an email alert, if the subscription offers that menu.
- Stop live runs at any time with `bash infra/killswitch.sh off` (replays keep working) and re-enable them with `on`.
- Delete all Azure resources with `bash infra/teardown.sh`.
- The student credits expire after 12 months.

### 7. Finalize [MANUAL]
Add 2–3 screenshots of the live site to `docs/img/` and link them in README.md. Set the author name and links in README.md and
`GITHUB_URL`, and test the site on a phone.

## Troubleshooting
- **RequestDisallowedByAzure or a region error:** use a region listed by the preflight script.
- **No model quota in Foundry:** use Route A. The application works with any of the supported providers.
- **Image pull fails:** the GHCR package is still private.
- **Slow first page load:** the container was scaled to zero and needs a few seconds to start. This is the trade-off for near-zero cost.
- **"Live runs paused":** a guard has triggered (daily cap, budget or cooldown) or the kill switch is off. This is intended behavior.
