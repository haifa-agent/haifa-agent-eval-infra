#!/usr/bin/env bash
# Haifa Agent Remote Source Preparation
# Usage: source-prepare.sh <runId> <productUrl> <productSha> <docsUrl> <docsSha> <testConfigUrl> <testConfigSha> <keyPath>
set -euo pipefail

RUN_ID="${1:-}"
PRODUCT_URL="${2:-}"
PRODUCT_SHA="${3:-}"
DOCS_URL="${4:-}"
DOCS_SHA="${5:-}"
TEST_CONFIG_URL="${6:-}"
TEST_CONFIG_SHA="${7:-}"
KEY_PATH="${8:-}"

if [[ -z "$RUN_ID" || -z "$PRODUCT_URL" || -z "$PRODUCT_SHA" || -z "$DOCS_URL" || -z "$DOCS_SHA" || -z "$TEST_CONFIG_URL" || -z "$TEST_CONFIG_SHA" || -z "$KEY_PATH" ]]; then
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
DOCS_DIR="$PRODUCT_DIR/docs"
TEST_CONFIG_DIR="$PRODUCT_DIR/test-config"

mkdir -p "$WORKTREE_BASE"

GIT_SSH_CMD="ssh -i $KEY_PATH -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes -o BatchMode=yes"

clone_and_pin() {
  local url="$1"
  local sha="$2"
  local dir="$3"
  local name="$4"

  echo "[source-prepare] Fetching $name ($sha) into $dir..."
  if [[ ! -d "$dir/.git" ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git clone --no-checkout "$url" "$dir"
  fi

  pushd "$dir" >/dev/null
  GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch --depth=1 origin "$sha" || GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin "$sha"
  git checkout -f "$sha"

  # Verify commit sha matches
  local current_sha
  current_sha="$(git rev-parse HEAD)"
  if [[ "$current_sha" != "$sha" ]]; then
    echo "[source-prepare] ERROR: $name checkout mismatch. Expected $sha, got $current_sha"
    exit 1
  fi

  # Verify working tree is clean
  local status
  status="$(git status --porcelain)"
  if [[ -n "$status" ]]; then
    echo "[source-prepare] ERROR: $name repository is not clean: $status"
    exit 1
  fi
  popd >/dev/null
}

clone_and_pin "$PRODUCT_URL" "$PRODUCT_SHA" "$PRODUCT_DIR" "product"
clone_and_pin "$DOCS_URL" "$DOCS_SHA" "$DOCS_DIR" "docs"
clone_and_pin "$TEST_CONFIG_URL" "$TEST_CONFIG_SHA" "$TEST_CONFIG_DIR" "test-config"

# Generate source manifest
MANIFEST_PATH="$WORKTREE_BASE/source-manifest.json"
cat <<EOF > "$MANIFEST_PATH"
{
  "runId": "$RUN_ID",
  "generatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "repositories": {
    "product": {
      "url": "$PRODUCT_URL",
      "commit": "$PRODUCT_SHA"
    },
    "docs": {
      "url": "$DOCS_URL",
      "commit": "$DOCS_SHA"
    },
    "testConfig": {
      "url": "$TEST_CONFIG_URL",
      "commit": "$TEST_CONFIG_SHA"
    }
  }
}
EOF

echo "[source-prepare] Source manifest created at $MANIFEST_PATH"
