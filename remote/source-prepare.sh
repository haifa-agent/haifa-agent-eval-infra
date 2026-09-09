#!/usr/bin/env bash
# Haifa Agent Remote Source Preparation
# Usage: source-prepare.sh <runId> <productUrl> <productRef> <docsUrl> <docsRef> <testConfigUrl> <testConfigRef> <keyPath>
set -euo pipefail

RUN_ID="${1:-}"
PRODUCT_URL="${2:-}"
PRODUCT_REF="${3:-}"
DOCS_URL="${4:-}"
DOCS_REF="${5:-}"
TEST_CONFIG_URL="${6:-}"
TEST_CONFIG_REF="${7:-}"
KEY_PATH="${8:-}"

if [[ -z "$RUN_ID" || -z "$PRODUCT_URL" || -z "$PRODUCT_REF" || -z "$DOCS_URL" || -z "$DOCS_REF" || -z "$TEST_CONFIG_URL" || -z "$TEST_CONFIG_REF" || -z "$KEY_PATH" ]]; then
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
  local ref="$2"
  local dir="$3"
  local name="$4"

  echo "[source-prepare] Fetching $name ($ref) into $dir..."
  if [[ ! -d "$dir/.git" ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git clone --no-checkout "$url" "$dir"
  fi

  pushd "$dir" >/dev/null
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin "$ref" || GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin
    git checkout -f "$ref" || git checkout -f FETCH_HEAD
    local current_sha
    current_sha="$(git rev-parse HEAD)"
    if [[ "$current_sha" != "$ref" ]]; then
      echo "[source-prepare] ERROR: $name checkout mismatch. Expected $ref, got $current_sha"
      exit 1
    fi
    echo "[source-prepare] $name pinned at commit: $current_sha"
  else
    # Branch mode: fetch the latest commit of the branch
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin "$ref" || GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch origin
    git checkout -f FETCH_HEAD
    local current_sha
    current_sha="$(git rev-parse HEAD)"
    echo "[source-prepare] $name pinned at branch '$ref' latest commit: $current_sha"
  fi

  if [[ -f .git/shallow ]]; then
    GIT_SSH_COMMAND="$GIT_SSH_CMD" git fetch --unshallow origin 2>/dev/null || true
  fi

  # Verify working tree is clean (allowing sub-repos docs/ and test-config/)
  local status
  status="$(git status --porcelain | grep -vE "^\?\? (docs|test-config)/" || true)"
  if [[ -n "$status" ]]; then
    echo "[source-prepare] ERROR: $name repository is not clean: $status"
    exit 1
  fi
  popd >/dev/null
}

clone_and_pin "$PRODUCT_URL" "$PRODUCT_REF" "$PRODUCT_DIR" "product"
clone_and_pin "$DOCS_URL" "$DOCS_REF" "$DOCS_DIR" "docs"
clone_and_pin "$TEST_CONFIG_URL" "$TEST_CONFIG_REF" "$TEST_CONFIG_DIR" "test-config"

PRODUCT_ACTUAL_SHA="$(git -C "$PRODUCT_DIR" rev-parse HEAD)"
DOCS_ACTUAL_SHA="$(git -C "$DOCS_DIR" rev-parse HEAD)"
TEST_CONFIG_ACTUAL_SHA="$(git -C "$TEST_CONFIG_DIR" rev-parse HEAD)"

# Generate source manifest
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
    },
    "docs": {
      "url": "$DOCS_URL",
      "commit": "$DOCS_ACTUAL_SHA",
      "ref": "$DOCS_REF"
    },
    "testConfig": {
      "url": "$TEST_CONFIG_URL",
      "commit": "$TEST_CONFIG_ACTUAL_SHA",
      "ref": "$TEST_CONFIG_REF"
    }
  }
}
EOF

echo "[source-prepare] Source manifest created at $MANIFEST_PATH"

# Ensure haifa-eval user has full permissions to execute tests and write build artifacts
if id -u haifa-eval >/dev/null 2>&1; then
  sudo chown -R haifa-eval:haifa-eval "$WORKTREE_BASE" 2>/dev/null || chown -R haifa-eval:haifa-eval "$WORKTREE_BASE"
  sudo chmod -R u+rwX,g+rwX "$WORKTREE_BASE" 2>/dev/null || true
fi
