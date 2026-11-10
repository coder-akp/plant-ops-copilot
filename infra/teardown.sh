#!/usr/bin/env bash
# Delete all resources this project created in Azure (the whole resource group) so that no further cost can accrue.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
RG="${RG:-rg-plantops}"
read -r -p "Delete resource group '$RG' and everything in it? Type the group name to confirm: " ANSWER
[ "$ANSWER" = "$RG" ] || { echo "Cancelled."; exit 1; }
az group delete -n "$RG" --yes --no-wait
echo "Deletion started."
