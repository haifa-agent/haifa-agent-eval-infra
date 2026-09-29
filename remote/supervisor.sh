#!/usr/bin/env bash
# Haifa Agent Remote Autonomous-Delivery Supervisor
# Usage: supervisor.sh <runId> <ladderSpecJsonPath>
#
# Reads a JSON run spec, builds the Coding Agent distribution from the frozen
# product source when required, then launches the autonomous-delivery ladder
# runner inside a systemd transient unit so it survives SSH disconnection.
set -euo pipefail

RUN_ID="${1:-}"
SPEC_PATH="${2:-}"

if [[ -z "$RUN_ID" || -z "$SPEC_PATH" || ! -f "$SPEC_PATH" ]]; then
  echo "[supervisor] ERROR: Usage: supervisor.sh <runId> <specPath>"
  exit 1
fi

RUN_USER="$(jq -r '.runUser' "$SPEC_PATH")"
WORKTREE="$(jq -r '.worktree' "$SPEC_PATH")"
AGENT_DIST="$(jq -r '.agentDistDir' "$SPEC_PATH")"
CACHE_DIR="$(jq -r '.assetsCacheDir' "$SPEC_PATH")"
OUTPUT_DIR="$(jq -r '.outputDir' "$SPEC_PATH")"
RUN_LADDER="$(jq -r '.runLadder' "$SPEC_PATH")"
CASE_SET="$(jq -r '.caseSet' "$SPEC_PATH")"
CASES="$(jq -r '.cases' "$SPEC_PATH")"
REPEAT="$(jq -r '.repeat' "$SPEC_PATH")"
TIMEOUT_SCALE="$(jq -r '.timeoutScale' "$SPEC_PATH")"
MODEL="$(jq -r '.model' "$SPEC_PATH")"
APPROVAL="$(jq -r '.approval' "$SPEC_PATH")"
REHEARSE="$(jq -r '.rehearse' "$SPEC_PATH")"
ACTION="$(jq -r '.action // "run"' "$SPEC_PATH")"
SECRETS_PATH="$(jq -r '.secretsPath' "$SPEC_PATH")"

CONTROL_DIR="/var/lib/haifa-eval/runs/$RUN_ID/control"
mkdir -p "$CONTROL_DIR"
JOURNAL_FILE="$CONTROL_DIR/ladder.journal"
EXIT_FILE="$CONTROL_DIR/ladder.exit"
BUILD_LOG="$CONTROL_DIR/agent-build.log"

UNIT_NAME="haifa-eval-$RUN_ID-ladder"

raw_java="$(readlink -f "$(command -v java)")"
JAVA_HOME_DIR="$(dirname "$(dirname "$raw_java")")"

echo "[supervisor] Preparing writable directories..."
mkdir -p "$AGENT_DIST" "$CACHE_DIR" "$OUTPUT_DIR"
chown -R "$RUN_USER:$RUN_USER" "$AGENT_DIST" "$CACHE_DIR" "$OUTPUT_DIR" 2>/dev/null || true

# Build the Coding Agent distribution from the frozen product source if absent.
if [[ "$REHEARSE" == "true" ]]; then
  echo "[supervisor] Rehearse mode: skipping agent distribution build."
elif [[ ! -f "$AGENT_DIST/haifa-agent.jar" ]]; then
  echo "[supervisor] Building Coding Agent distribution into $AGENT_DIST (log: $BUILD_LOG)..."
  set +e
  sudo -u "$RUN_USER" env JAVA_HOME="$JAVA_HOME_DIR" \
    bash "$WORKTREE/scripts/package-local-coding-agent.sh" "$AGENT_DIST" \
    > "$BUILD_LOG" 2>&1
  build_rc=$?
  set -e
  if [[ $build_rc -ne 0 || ! -f "$AGENT_DIST/haifa-agent.jar" ]]; then
    echo "[supervisor] ERROR: Agent distribution build failed (rc=$build_rc); see $BUILD_LOG"
    echo "$build_rc" > "$EXIT_FILE"
    exit "$build_rc"
  fi
else
  echo "[supervisor] Reusing existing agent distribution at $AGENT_DIST"
fi

# The Coding Agent persists workspace authorizations in its runtime database. Every run recreates
# the case workspaces at the same paths with new directory identities, so a database left over
# from a previous run fails closed with HostWorkspaceScopeException. Start each run from a clean
# agent database.
rm -f "$AGENT_DIST/data/runtime.db" "$AGENT_DIST/data/runtime.db-wal" \
      "$AGENT_DIST/data/runtime.db-shm" 2>/dev/null || true

LADDER_ARGS=(
  "$ACTION"
  --agent "$AGENT_DIST/haifa-coding"
  --model "$MODEL"
  --approval "$APPROVAL"
  --case-set "$CASE_SET"
  --timeout-scale "$TIMEOUT_SCALE"
  --output "$OUTPUT_DIR"
  --cache-dir "$CACHE_DIR"
)
if [[ -n "$CASES" && "$CASES" != "null" ]]; then
  LADDER_ARGS+=( --cases "$CASES" )
fi
if [[ -n "$REPEAT" && "$REPEAT" != "null" ]]; then
  LADDER_ARGS+=( --repeat "$REPEAT" )
fi
if [[ "$ACTION" == "run" && "$REHEARSE" == "true" ]]; then
  LADDER_ARGS+=( --rehearse --skip-gates )
fi

echo "[supervisor] Launching transient unit $UNIT_NAME..."
sudo systemctl stop "$UNIT_NAME" 2>/dev/null || true
sudo systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
sudo rm -f "/run/systemd/transient/$UNIT_NAME.service" 2>/dev/null || true
sudo systemctl daemon-reload 2>/dev/null || true

set +e
sudo systemd-run \
  --unit="$UNIT_NAME" \
  --collect \
  --description="Haifa Evaluation $RUN_ID autonomous-delivery ladder" \
  --uid="$RUN_USER" \
  --gid="$RUN_USER" \
  --property=EnvironmentFile="$SECRETS_PATH" \
  --property=Environment="HOME=/home/$RUN_USER" \
  --property=Environment="JAVA_HOME=$JAVA_HOME_DIR" \
  --property=Environment="HAIFA_LADDER_ALLOW_REAL_PROVIDER=true" \
  --property=Environment="LANG=C.UTF-8" \
  --property=Environment="LC_ALL=C.UTF-8" \
  --property=LimitNOFILE=65536 \
  --working-directory="$WORKTREE" \
  --wait \
  --pipe \
  /bin/bash "$RUN_LADDER" "${LADDER_ARGS[@]}" 2>&1 | tee "$JOURNAL_FILE"
EXIT_STATUS="${PIPESTATUS[0]}"
set -e

echo "$EXIT_STATUS" > "$EXIT_FILE"
echo "[supervisor] Unit $UNIT_NAME finished with status: $EXIT_STATUS"

# Best-effort resource usage report (run only; a check produces no runs).
if [[ "$ACTION" == "run" && -x "$RUN_LADDER" ]]; then
  sudo -u "$RUN_USER" env HOME="/home/$RUN_USER" \
    bash "$RUN_LADDER" stats --run "$OUTPUT_DIR" \
    --runtime-db "$AGENT_DIST/data/runtime.db" >/dev/null 2>&1 || true
fi

if [[ "$EXIT_STATUS" != "0" ]]; then
  exit "$EXIT_STATUS"
fi
