#!/usr/bin/env bash
# Haifa Agent Remote Source Preparation (product repository only)
# Usage: source-prepare.sh <runId> <productUrl> <productRef> <keyPath>
#
# The autonomous-delivery ladder runner fetches its own case assets at run time;
# only the product repository is frozen here so the agent distribution can be built
# from an exact commit.
set -euo pipefail

RUN_ID="${1:-}"
PRODUCT_URL="${2:-}"
PRODUCT_REF="${3:-}"
KEY_PATH="${4:-}"

if [[ -z "$RUN_ID" || -z "$PRODUCT_URL" || -z "$PRODUCT_REF" || -z "$KEY_PATH" ]]; then
  echo "[source-prepare] ERROR: Missing required arguments"
  exit 1
fi

cleanup_key() {
  if [[ -f "$KEY_PATH" ]]; then
    rm -f "$KEY_PATH"
    echo "[source-prepare] Cleaned up temporary GitHub SSH key."
  fi
}
trap cleanup_key EXIT INT TERM

WORKTREE_BASE="/var/lib/haifa-eval/worktrees/$RUN_ID"
PRODUCT_DIR="$WORKTREE_BASE/haifa-agent"

mkdir -p "$WORKTREE_BASE"

GIT_SSH_CMD="ssh -i $KEY_PATH -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes -o BatchMode=yes"

clone_and_pin() {
  local url="$1"
  local ref="$2"
  local dir="$3"
  local name="$4"

  echo "[source-prepare] Fetching $name ($ref) into $dir..."
  if [[ ! -d "$dir/.git" ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git clone --no-checkout "$url" "$dir"
  fi

  pushd "$dir" >/dev/null
  GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin "$ref" || GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    git checkout -f "$ref" || git checkout -f FETCH_HEAD
    local current_sha
    current_sha="$(git rev-parse HEAD)"
    if [[ "$current_sha" != "$ref" ]]; then
      echo "[source-prepare] ERROR: $name checkout mismatch. Expected $ref, got $current_sha"
      exit 1
    fi
    echo "[source-prepare] $name pinned at commit: $current_sha"
  else
    git checkout -f FETCH_HEAD
    local current_sha
    current_sha="$(git rev-parse HEAD)"
    echo "[source-prepare] $name pinned at branch '$ref' latest commit: $current_sha"
  fi

  if [[ -f .git/shallow ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch --unshallow origin 2>/dev/null || true
  fi

  local status
  status="$(git status --porcelain)"
  if [[ -n "$status" ]]; then
    echo "[source-prepare] ERROR: $name repository is not clean: $status"
    exit 1
  fi
  popd >/dev/null
}

clone_and_pin "$PRODUCT_URL" "$PRODUCT_REF" "$PRODUCT_DIR" "product"

PRODUCT_ACTUAL_SHA="$(git -C "$PRODUCT_DIR" rev-parse HEAD)"

MANIFEST_PATH="$WORKTREE_BASE/source-manifest.json"
cat <<EOF > "$MANIFEST_PATH"
{
  "runId": "$RUN_ID",
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "repositories": {
    "product": {
      "url": "$PRODUCT_URL",
      "commit": "$PRODUCT_ACTUAL_SHA",
      "ref": "$PRODUCT_REF"
    }
  }
}
EOF

echo "[source-prepare] Source manifest created at $MANIFEST_PATH"

if id -u haifa-eval >/dev/null 2>&1; then
  sudo chown -R haifa-eval:haifa-eval "$WORKTREE_BASE" 2>/dev/null || chown -R haifa-eval:haifa-eval "$WORKTREE_BASE"
  sudo chmod -R u+rwX,g+rwX "$WORKTREE_BASE" 2>/dev/null || true
fi
