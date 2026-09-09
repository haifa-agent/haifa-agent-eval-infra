#!/usr/bin/env bash
# Haifa Agent Remote Harness Supervisor
# Usage: supervisor.sh <runId> <suiteId> <planPath> <approveBudget> <worktreeDir> <secretsPath>
set -euo pipefail

RUN_ID="${1:-}"
SUITE_ID="${2:-}"
PLAN_PATH="${3:-}"
APPROVE_BUDGET="${4:-}"
WORKTREE_DIR="${5:-}"
SECRETS_PATH="${6:-}"
RUN_USER="${7:-haifa-eval}"

if [[ -z "$RUN_ID" || -z "$SUITE_ID" || -z "$PLAN_PATH" || -z "$APPROVE_BUDGET" || -z "$WORKTREE_DIR" || -z "$SECRETS_PATH" ]]; then
  echo "[supervisor] ERROR: Missing required arguments"
  exit 1
fi

CONTROL_DIR="/var/lib/haifa-eval/runs/$RUN_ID/control"
mkdir -p "$CONTROL_DIR"
sudo chown -R "$RUN_USER:$RUN_USER" "$CONTROL_DIR" 2>/dev/null || true
sudo chmod -R 775 "$CONTROL_DIR" 2>/dev/null || true
JOURNAL_FILE="$CONTROL_DIR/$SUITE_ID.journal"
EXIT_FILE="$CONTROL_DIR/$SUITE_ID.exit"

UNIT_NAME="haifa-eval-$RUN_ID-$SUITE_ID"

echo "[supervisor] Launching transient unit $UNIT_NAME..."

# Ensure java home is set from javac
eval_java="$(readlink -f "$(command -v java)")"
eval_java_home="$(dirname "$(dirname "$eval_java")")"

RUN_SCRIPT="$WORKTREE_DIR/haifa-agent/test-config/scripts/run-suite.sh"
if [[ ! -x "$RUN_SCRIPT" ]]; then
  chmod +x "$RUN_SCRIPT" 2>/dev/null || true
fi

# Ensure Utility MCP server is available on port 20002
MCP_ENSURE_SCRIPT="$CONTROL_DIR/ensure-mcp.sh"
if [[ -f "$MCP_ENSURE_SCRIPT" ]]; then
  echo "[supervisor] Verifying Utility MCP service availability on port 20002..."
  bash "$MCP_ENSURE_SCRIPT" "$RUN_USER" 20002 || true
fi

# Run via systemd-run to survive SSH disconnection
sudo systemd-run \
  --unit="$UNIT_NAME" \
  --description="Haifa Evaluation $RUN_ID $SUITE_ID" \
  --uid="$RUN_USER" \
  --gid="$RUN_USER" \
  --property=EnvironmentFile="$SECRETS_PATH" \
  --property=Environment="JAVA_HOME=$eval_java_home" \
  --property=Environment="LANG=C.UTF-8" \
  --property=Environment="LC_ALL=C.UTF-8" \
  --property=LimitNOFILE=65536 \
  --working-directory="$WORKTREE_DIR/haifa-agent" \
  --wait \
  --pipe \
  /bin/bash "$RUN_SCRIPT" run --plan "$PLAN_PATH" --approve-budget "$APPROVE_BUDGET" 2>&1 | tee "$JOURNAL_FILE" || true

# Extract unit exit code
EXIT_STATUS="$(systemctl show "$UNIT_NAME" --property=ExecMainStatus --value 2>/dev/null || echo "1")"
echo "$EXIT_STATUS" > "$EXIT_FILE"
echo "[supervisor] Unit $UNIT_NAME finished with status: $EXIT_STATUS"
if [[ "$EXIT_STATUS" != "0" ]]; then
  exit "$EXIT_STATUS"
fi
