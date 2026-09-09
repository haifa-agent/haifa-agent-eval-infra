#!/usr/bin/env bash
# Haifa Agent Remote Run Cleanup
# Usage: cleanup.sh <runId> [--include-evidence]
set -euo pipefail

RUN_ID="${1:-}"
INCLUDE_EVIDENCE="${2:-}"

if [[ -z "$RUN_ID" ]]; then
  echo "[cleanup] ERROR: runId is required"
  exit 1
fi

# Validate runId contains only allowed characters
if [[ ! "$RUN_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "[cleanup] ERROR: Invalid runId format: $RUN_ID"
  exit 1
fi

# Refuse dangerous targets
if [[ "$RUN_ID" == "/" || "$RUN_ID" == "*" || "$RUN_ID" == ".." || "$RUN_ID" == "." ]]; then
  echo "[cleanup] ERROR: Refusing to clean dangerous target: $RUN_ID"
  exit 1
fi

echo "[cleanup] Stopping any running units for $RUN_ID..."
for unit in $(systemctl list-units --all --plain --no-legend "haifa-eval-$RUN_ID-*" 2>/dev/null | awk '{print $1}'); do
  sudo systemctl stop "$unit" 2>/dev/null || true
  sudo systemctl reset-failed "$unit" 2>/dev/null || true
done

echo "[cleanup] Removing ephemeral secrets in /run/haifa-eval/$RUN_ID..."
sudo rm -rf "/run/haifa-eval/$RUN_ID"

echo "[cleanup] Removing worktrees and plans in /var/lib/haifa-eval/ for $RUN_ID..."
sudo rm -rf "/var/lib/haifa-eval/worktrees/$RUN_ID"
sudo rm -rf "/var/lib/haifa-eval/plans/$RUN_ID"
sudo rm -rf "/var/lib/haifa-eval/runs/$RUN_ID"

if [[ "$INCLUDE_EVIDENCE" == "--include-evidence" ]]; then
  echo "[cleanup] Removing remote evidence in /var/lib/haifa-eval/evidence/$RUN_ID..."
  sudo rm -rf "/var/lib/haifa-eval/evidence/$RUN_ID"
fi

echo "[cleanup] Cleanup for $RUN_ID completed."
