#!/usr/bin/env bash
# Switch live (paid or rate-limited) agent runs off or on without redeploying:
#   bash infra/killswitch.sh off      # visitors can still use the recorded replays
#   bash infra/killswitch.sh on
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
RG="${RG:-rg-plantops}"; APP="${APP:-plantops-copilot}"
case "${1:-}" in
  off) VALUE=false ;;
  on)  VALUE=true ;;
  *) echo "usage: bash infra/killswitch.sh on|off"; exit 1 ;;
esac
az containerapp update -n "$APP" -g "$RG" --set-env-vars "LIVE_ENABLED=$VALUE" -o none
echo "LIVE_ENABLED=$VALUE"
