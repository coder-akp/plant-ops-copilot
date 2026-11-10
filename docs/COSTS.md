# Cost design

Goal: keep the $100 student credit almost untouched.

| Decision | Reason |
|---|---|
| Container Apps, consumption plan, `min-replicas 0`, `max-replicas 1`, 0.5 vCPU / 1 GiB | Billing applies only while requests are handled. The monthly free grant (180,000 vCPU-s, 360,000 GiB-s, 2M requests, per Microsoft's pricing page) covers a portfolio site |
| Image on GitHub Container Registry | Azure Container Registry has a monthly fee |
| `--logs-destination none` | No Log Analytics ingestion cost |
| Data built into the image (DuckDB file) | No database service required |
| Recorded replays as the default | Most visitors cost exactly $0 |
| Live runs: 25 per day in total, 3 per IP per day, 15 s cooldown, $0.50 estimated daily cap, one run at a time, 60k token cap, 12 tool calls, 120 s | Bounded worst case |
| Kill switch and optional access code | Immediate stop; live runs can be limited to selected people |
| Gemini free tier as the default model route | $0 model cost |

**Limits.** Guard counters are held in memory and reset when the container scales to zero, so they do not form a hard
financial limit. The hard backstops are (1) the tokens-per-minute quota set on the Foundry deployment, (2) an Azure
budget alert and (3) the kill switch. A student subscription has no payment card attached, and the credit is finite.
The per-run cost is an estimate (roughly cents on a small model) and has not been measured with a real model. The UI shows the
running estimate and `scripts/record_replays.py` prints actual token counts, so a single measurement allows
`PRICE_IN_PER_M` / `PRICE_OUT_PER_M` to be set accurately. Azure prices were not verified against the live pricing page and should be confirmed there.
