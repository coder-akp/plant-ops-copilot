"""Check what the Azure subscription supports before any resources are created.

    az login
    python -m scripts.azure_preflight

Azure for Students subscriptions restrict the regions available for deployment, and
some have no Azure OpenAI / Foundry quota. Apart from registering the Microsoft.App
resource provider (needed to query Container Apps regions), the script only reads
subscription data. It reports:
  * the regions allowed by policy,
  * where Azure Container Apps is available within those regions,
  * whether model quota exists for a Foundry deployment in those regions.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

WANTED_MODELS = ("gpt-5-mini", "gpt-5-nano", "gpt-4.1-mini", "gpt-4o-mini")


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def region_lookup(locations: list[dict]) -> dict[str, str]:
    """Map normalized region names and display names to the programmatic region name."""
    out: dict[str, str] = {}
    for loc in locations:
        out[norm(loc["name"])] = loc["name"]
        if loc.get("displayName"):
            out[norm(loc["displayName"])] = loc["name"]
    return out


def allowed_regions(assignments: list[dict], lookup: dict[str, str]) -> set[str] | None:
    """Return the regions allowed by the 'Allowed resource deployment regions' policy, or None if no restriction is found."""
    found: set[str] = set()
    seen_policy = False
    for item in assignments or []:
        values = item.get("allowed")
        if values:
            seen_policy = True
            found |= {lookup.get(norm(v), norm(v)) for v in values}
    return found if seen_policy else None


def supported_regions(names: list[str], lookup: dict[str, str]) -> set[str]:
    return {lookup.get(norm(n), norm(n)) for n in names or []}


def model_quota(usage: list[dict]) -> list[tuple[str, float, float]]:
    rows = []
    for u in usage or []:
        name = (u.get("name") or {}).get("value", "")
        if name.startswith("OpenAI.") and any(m in name for m in WANTED_MODELS):
            rows.append((name, float(u.get("limit") or 0), float(u.get("currentValue") or 0)))
    return rows


def az(*args: str):
    exe = shutil.which("az")
    if not exe:
        sys.exit("Azure CLI ('az') not found. Install it first: https://learn.microsoft.com/cli/azure/install-azure-cli")
    proc = subprocess.run([exe, *args, "-o", "json", "--only-show-errors"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "az failed")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def main() -> int:
    try:
        acct = az("account", "show")
    except RuntimeError as exc:
        print(f"Not logged in? Run 'az login' first.\n{exc}")
        return 1
    print(f"Subscription: {acct['name']}  ({acct['id']})  state={acct['state']}")

    lookup = region_lookup(az("account", "list-locations"))
    try:
        policies = az(
            "policy", "assignment", "list", "--query",
            "[?displayName=='Allowed resource deployment regions'].{allowed:parameters.allowedLocations.value}",
        )
    except RuntimeError as exc:
        policies = []
        print(f"(could not read policy assignments: {exc})")
    allowed = allowed_regions(policies, lookup)
    print("Allowed regions:", ", ".join(sorted(allowed)) if allowed else "no region restriction found")

    try:
        az("provider", "register", "--namespace", "Microsoft.App")  # harmless; required to query Container Apps regions
        locs = az("provider", "show", "-n", "Microsoft.App", "--query",
                  "resourceTypes[?resourceType=='managedEnvironments'].locations | [0]")
    except RuntimeError as exc:
        print(f"Could not read Container Apps regions: {exc}")
        return 1
    supported = supported_regions(locs, lookup)
    candidates = sorted(supported & allowed) if allowed else sorted(supported)
    print("Container Apps usable in:", ", ".join(candidates) if candidates else "none of the allowed regions")

    foundry: dict[str, list[tuple[str, float, float]]] = {}
    for region in (candidates or [])[:6]:
        try:
            rows = [r for r in model_quota(az("cognitiveservices", "usage", "list", "-l", region)) if r[1] > 0]
        except RuntimeError:
            rows = []
        if rows:
            foundry[region] = rows
    print()
    if foundry:
        print("Foundry model quota found (limit > 0):")
        for region, rows in foundry.items():
            for name, limit, used in rows:
                print(f"  {region:16} {name:45} limit={limit:g} used={used:g}")
    else:
        print("No Foundry/Azure OpenAI quota found in the usable regions (limit is 0 or not readable).")

    print("\nRECOMMENDATION")
    if not candidates:
        print("  Container Apps is not available in the allowed regions. Do not deploy yet; see docs/START_HERE.md, section 'If something is blocked'.")
        return 2
    print(f"  Host the app in: {candidates[0]}   (set LOCATION={candidates[0]})")
    if foundry:
        print("  Foundry route is possible: create the project/deployment in a region listed above.")
    else:
        print("  Use the Gemini free tier for the model (LLM_PROVIDER=gemini). It costs nothing and avoids the quota problem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
