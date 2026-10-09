#!/usr/bin/env bash
# Haifa Agent Remote Harbor/Eval Control Plane Supervisor
# Usage: supervisor-harbor.sh <runId> <evalsSpecJsonPath>
#
# Reads the JSON evals run spec, prepares a Harbor job work directory, and runs
# the frozen haifa-agent-evals CLI (admit / doctor / run / collect / report)
# inside a systemd transient unit so it survives SSH disconnection.
# Credentials (e.g. BIGMODEL_API_KEY) come from the injected secrets.env
# EnvironmentFile; only the non-secret BIGMODEL_API_BASE is set explicitly.
set -euo pipefail

RUN_ID="${1:-}"
SPEC_PATH="${2:-}"

if [[ -z "$RUN_ID" || -z "$SPEC_PATH" || ! -f "$SPEC_PATH" ]]; then
  echo "[supervisor-harbor] ERROR: Usage: supervisor-harbor.sh <runId> <specPath>"
  exit 1
fi

RUN_USER="$(jq -r '.runUser' "$SPEC_PATH")"
WORKTREE="$(jq -r '.worktree' "$SPEC_PATH")"
EVAL_ID="$(jq -r '.evalId' "$SPEC_PATH")"
API_BASE_URL="$(jq -r '.apiBaseUrl // empty' "$SPEC_PATH")"
OUTPUT_DIR="$(jq -r '.outputDir' "$SPEC_PATH")"
ACTION="$(jq -r '.action // "run"' "$SPEC_PATH")"
SECRETS_PATH="$(jq -r '.secretsPath' "$SPEC_PATH")"

CONTROL_DIR="/var/lib/haifa-eval/runs/$RUN_ID/control"
mkdir -p "$CONTROL_DIR"
JOURNAL_FILE="$CONTROL_DIR/evals.journal"
EXIT_FILE="$CONTROL_DIR/evals.exit"
SETUP_LOG="$CONTROL_DIR/setup.log"

UNIT_NAME="haifa-eval-$RUN_ID-evals"

UV_BIN="/opt/haifa-eval/bin/uv"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "[supervisor-harbor] ERROR: uv binary not found at /opt/haifa-eval/bin/uv or on PATH"
  echo 1 > "$EXIT_FILE"
  exit 1
fi

CONFIG_RELPATH="evals/$EVAL_ID.yaml"
if [[ ! -f "$WORKTREE/$CONFIG_RELPATH" ]]; then
  echo "[supervisor-harbor] ERROR: eval config not found in frozen checkout: $CONFIG_RELPATH"
  echo 1 > "$EXIT_FILE"
  exit 1
fi

RUN_HOME_ROOT="/var/lib/haifa-eval/runs/$RUN_ID/harbor"
# Timestamped job dir: host-side Terminus-2 requires BIGMODEL secrets mapped to
# LiteLLM's ZAI_* names (see derived env below), and evals runs need unique
# work dirs per invocation.
WORK_DIR="$RUN_HOME_ROOT/job-$(date +%Y%m%dT%H%M%SZ)"

echo "[supervisor-harbor] Preparing work directories..."
# WORK_DIR must NOT pre-exist: `evals run --work-dir` creates it itself. The
# RUN_HOME_ROOT and OUTPUT_DIR are created here as root, then handed to the
# unprivileged run user so the driver can create subdirectories.
mkdir -p "$RUN_HOME_ROOT" "$OUTPUT_DIR"
chown -R "$RUN_USER:$RUN_USER" "$RUN_HOME_ROOT" "$OUTPUT_DIR" 2>/dev/null || true

if [[ -z "${API_BASE_URL}" ]]; then
  API_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
fi

# LiteLLM's zai/ provider reads ZAI_API_KEY / ZAI_API_BASE from the *host*
# process env (Terminus-2 runs its LLM calls inside the harbor process). The
# user-facing names are BIGMODEL_*; derive the ZAI names here into a tmpfs
# env file. Values are never printed.
derived_secret_dir="$(dirname "$SECRETS_PATH")"
DERIVED_ENV="$derived_secret_dir/secrets-derived.env"
echo "[supervisor-harbor] Deriving provider environment (log-free)..."
sudo bash -s -- "$RUN_USER" "$SECRETS_PATH" "$DERIVED_ENV" "${API_BASE_URL}" <<'DERIVE'
set -euo pipefail
run_user="$1"
secrets_path="$2"
derived_env="$3"
api_base_url="${4:-}"

zai_api_base="$api_base_url"
if [[ -z "$zai_api_base" ]]; then
  zai_api_base="https://open.bigmodel.cn/api/paas/v4"
fi

# NOSET: values stay inside this file only. shellcheck disable=SC1090
source "$secrets_path"
{
  printf 'ZAI_API_KEY="%s"\n' "${BIGMODEL_API_KEY:-}"
  printf 'ZAI_API_BASE="%s"\n' "$zai_api_base"
  printf 'BIGMODEL_API_BASE="%s"\n' "$zai_api_base"
} > "$derived_env"
chmod 0600 "$derived_env"
chown "$run_user:$run_user" "$derived_env"
DERIVE

# uv.lock pins pypi.org; pypi.org is unreachable from cn snapshots, so swap
# the default index to the Aliyun PyPI mirror for every uv invocation in this run.
export UV_DEFAULT_INDEX="https://mirrors.aliyun.com/pypi/simple/"

echo "[supervisor-harbor] Syncing frozen evals repository (log: $SETUP_LOG)..."
set +e
sudo -u "$RUN_USER" env HOME="/home/$RUN_USER" UV_DEFAULT_INDEX="$UV_DEFAULT_INDEX" \
  bash -c "cd '$WORKTREE' && '$UV_BIN' sync --frozen --quiet" \
  > "$SETUP_LOG" 2>&1
sync_rc=$?
set -e
if [[ $sync_rc -ne 0 ]]; then
  echo "[supervisor-harbor] ERROR: uv sync failed (rc=$sync_rc); see $SETUP_LOG"
  echo "$sync_rc" > "$EXIT_FILE"
  exit "$sync_rc"
fi

# Per-run driver script executed inside the transient unit.
DRIVER_FILE="$CONTROL_DIR/evals-driver.sh"
cat > "$DRIVER_FILE" <<DRIVER
#!/usr/bin/env bash
set -euo pipefail
export HOME="/home/$RUN_USER"
cd "$WORKTREE"
UV="$UV_BIN"
EVALS=("$UV_BIN" run evals)
ADMISSION_DIR="$RUN_HOME_ROOT/admissions"
mkdir -p "\$ADMISSION_DIR"
ADMISSION="\$ADMISSION_DIR/$EVAL_ID.json"
CONFIG="$CONFIG_RELPATH"

"\${EVALS[@]}" admit --config "\$CONFIG" --output "\$ADMISSION"
echo "[driver] admission: \$(cat "\$ADMISSION" | jq -r .status)"

if [[ "$ACTION" == "check" ]]; then
  "\${EVALS[@]}" doctor --config "\$CONFIG" --admission "\$ADMISSION" \\
    --output "$OUTPUT_DIR/preflight.json"
  echo "[driver] check complete"
  exit 0
fi

if [[ "$ACTION" != "run" ]]; then
  echo "[driver] ERROR: unsupported action $ACTION"
  exit 2
fi

"\${EVALS[@]}" run --config "\$CONFIG" --admission "\$ADMISSION" --work-dir "$WORK_DIR"

"\${EVALS[@]}" collect --job-dir "$WORK_DIR" \\
  --output "$OUTPUT_DIR/results.csv" --eval-id "$EVAL_ID"

"\${EVALS[@]}" report --results "$OUTPUT_DIR/results.csv" \\
  --output "$OUTPUT_DIR/report.md"

"$UV_BIN" run python - "$OUTPUT_DIR/results.csv" "$OUTPUT_DIR/evals-summary.json" <<'SUMMARY'
import csv
import json
import sys
from pathlib import Path

rows = list(csv.DictReader(Path(sys.argv[1]).open(encoding="utf-8", newline="")))


def as_float(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except ValueError:
        return None


rewards = []
tasks = sorted({row.get("task_id", "") for row in rows})
passes = 0
for row in rows:
    reward = as_float(row.get("reward", ""))
    rewards.append(reward)
    if reward is not None and reward >= 1.0:
        passes += 1
rated = [value for value in rewards if value is not None]
summary = {
    "schemaVersion": 1,
    "kind": "haifa-evals-harbor",
    "evalId": "$EVAL_ID",
    "attemptCount": len(rows),
    "taskCount": len(tasks),
    "tasks": tasks,
    "candidates": sorted({row.get("candidate", "") for row in rows}) if rows else [],
    "rewardSum": sum(reward for reward in rated),
    "rewardMean": (sum(rated) / len(rated)) if rated else None,
    "passed": passes,
}
with Path(sys.argv[2]).open("w", encoding="utf-8") as stream:
    json.dump(summary, stream, indent=2)
    stream.write("\\n")
SUMMARY
echo "[driver] run complete"
DRIVER
chmod +x "$DRIVER_FILE"
chown "$RUN_USER:$RUN_USER" "$DRIVER_FILE" 2>/dev/null || true

echo "[supervisor-harbor] Launching transient unit $UNIT_NAME..."
sudo systemctl stop "$UNIT_NAME" 2>/dev/null || true
sudo systemctl reset-failed "$UNIT_NAME" 2>/dev/null || true
sudo rm -f "/run/systemd/transient/$UNIT_NAME.service" 2>/dev/null || true
sudo systemctl daemon-reload 2>/dev/null || true

set +e
sudo systemd-run \
  --unit="$UNIT_NAME" \
  --collect \
  --description="Haifa Evaluation $RUN_ID harbor evals" \
  --uid="$RUN_USER" \
  --gid="$RUN_USER" \
  --property=EnvironmentFile="$SECRETS_PATH" \
  --property=EnvironmentFile="$DERIVED_ENV" \
  --property=Environment="HOME=/home/$RUN_USER" \
  --property=Environment="UV_BIN=$UV_BIN" \
  --property=Environment="UV_DEFAULT_INDEX=$UV_DEFAULT_INDEX" \
  --property=Environment="BIGMODEL_API_BASE=$API_BASE_URL" \
  --property=Environment="LANG=C.UTF-8" \
  --property=Environment="LC_ALL=C.UTF-8" \
  --property=SupplementaryGroups=docker \
  --property=LimitNOFILE=65536 \
  --working-directory="$WORKTREE" \
  --wait \
  --pipe \
  /bin/bash "$DRIVER_FILE" 2>&1 | tee "$JOURNAL_FILE"
EXIT_STATUS="${PIPESTATUS[0]}"
set -e

echo "$EXIT_STATUS" > "$EXIT_FILE"
echo "[supervisor-harbor] Unit $UNIT_NAME finished with status: $EXIT_STATUS"
exit "$EXIT_STATUS"
