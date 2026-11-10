#!/usr/bin/env bash
# Deploy (or update) Plant Ops Copilot on Azure Container Apps with minimal cost:
#   * Consumption plan, scale to zero (min replicas 0), at most one replica
#   * Image pulled from GitHub Container Registry (no paid Azure Container Registry)
#   * Log storage disabled (no Log Analytics workspace cost)
# Requirements: Azure CLI logged in (az login) and these variables (shell or .env):
#   LOCATION  an allowed region, for example from: python -m scripts.azure_preflight
#   IMAGE     for example ghcr.io/<github-user>/plant-ops-copilot:latest (lower case)
# Optional: RG, ENV_NAME, APP; GHCR_USER and GHCR_TOKEN if the image package is private.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi

: "${LOCATION:?Set LOCATION to one of the allowed regions (run: python -m scripts.azure_preflight)}"
: "${IMAGE:?Set IMAGE, e.g. ghcr.io/<github-user>/plant-ops-copilot:latest}"
RG="${RG:-rg-plantops}"; ENV_NAME="${ENV_NAME:-cae-plantops}"; APP="${APP:-plantops-copilot}"

echo "== Subscription"; az account show --query "{name:name,id:id}" -o tsv
echo "== Preparing Azure CLI"
az extension add --name containerapp --upgrade --only-show-errors >/dev/null
az provider register --namespace Microsoft.App --wait --only-show-errors

SECRETS=(); ENVV=()
add_env()    { if [ -n "${2:-}" ]; then ENVV+=("$1=$2"); fi; }
add_secret() { if [ -n "${3:-}" ]; then SECRETS+=("$1=$3"); ENVV+=("$2=secretref:$1"); fi; }

add_env LLM_PROVIDER "${LLM_PROVIDER:-none}"
add_env GEMINI_MODEL "${GEMINI_MODEL:-}"
add_env AZURE_OPENAI_ENDPOINT "${AZURE_OPENAI_ENDPOINT:-}"
add_env AZURE_OPENAI_DEPLOYMENT "${AZURE_OPENAI_DEPLOYMENT:-}"
add_env AZURE_OPENAI_API_VERSION "${AZURE_OPENAI_API_VERSION:-}"
add_env AZURE_REASONING_EFFORT "${AZURE_REASONING_EFFORT:-}"
for v in PRICE_IN_PER_M PRICE_OUT_PER_M LIVE_ENABLED DAILY_MAX_RUNS PER_IP_MAX_RUNS DAILY_BUDGET_USD \
         LIVE_COOLDOWN_S MAX_RUN_TOKENS MAX_OUTPUT_TOKENS RUN_TIMEOUT_S GITHUB_URL; do
  add_env "$v" "${!v:-}"
done
add_secret google-api-key    GOOGLE_API_KEY       "${GOOGLE_API_KEY:-}"
add_secret azure-openai-key  AZURE_OPENAI_API_KEY "${AZURE_OPENAI_API_KEY:-}"
add_secret access-code       ACCESS_CODE          "${ACCESS_CODE:-}"

REGISTRY_ARGS=()
if [ -n "${GHCR_USER:-}" ] && [ -n "${GHCR_TOKEN:-}" ]; then
  REGISTRY_ARGS=(--registry-server ghcr.io --registry-username "$GHCR_USER" --registry-password "$GHCR_TOKEN")
fi

echo "== Resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" --only-show-errors -o none

if ! az containerapp env show -n "$ENV_NAME" -g "$RG" -o none 2>/dev/null; then
  echo "== Container Apps environment $ENV_NAME (no log storage)"
  az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$LOCATION" --logs-destination none --only-show-errors -o none
fi

if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  echo "== Updating $APP"
  if [ ${#SECRETS[@]} -gt 0 ]; then az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" -o none; fi
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars "${ENVV[@]}" -o none
else
  echo "== Creating $APP"
  az containerapp create -n "$APP" -g "$RG" --environment "$ENV_NAME" --image "$IMAGE" \
    --ingress external --target-port 8000 \
    --min-replicas 0 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
    ${SECRETS[@]+--secrets "${SECRETS[@]}"} \
    --env-vars "${ENVV[@]}" \
    ${REGISTRY_ARGS[@]+"${REGISTRY_ARGS[@]}"} -o none
fi

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo
echo "Done. Site URL: https://$FQDN"
echo "(The first visit after an idle period takes a few seconds while the container starts from zero.)"
