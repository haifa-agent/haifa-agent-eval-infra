#!/usr/bin/env bash
# Haifa Agent Remote Host Bootstrap (Harbor/Eval evaluation workload)
# Usage: bootstrap-harbor.sh [eval-user]
#
# Same baseline directory/user contract as bootstrap.sh, but instead of the
# JVM/Maven toolchain it installs Docker Engine + Compose v2 + uv, which are
# the requirements for running Harbor (Terminal-Bench) evaluations remotely.
set -euo pipefail

FACTS_DIR="/var/lib/haifa-eval/facts"
EVAL_USER="${1:-$USER}"
EVAL_HOME="/home/$EVAL_USER"
PACKAGES=(
  ca-certificates curl wget git openssh-client
  jq tar unzip zip xz-utils rsync
  docker.io docker-compose-v2
  build-essential
  python3 python3-venv python3-pip
  procps psmisc lsof acl util-linux locales tzdata
)

echo "[bootstrap-harbor] Checking passwordless sudo..."
sudo -n true || { echo "[bootstrap-harbor] ERROR: passwordless sudo required"; exit 1; }

echo "[bootstrap-harbor] Updating APT package index..."
sudo apt-get update -y

echo "[bootstrap-harbor] Installing baseline + Docker toolchain packages..."
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${PACKAGES[@]}"

echo "[bootstrap-harbor] Verifying Docker engine and Compose v2..."
sudo docker --version
sudo docker compose version

echo "[bootstrap-harbor] Ensuring dedicated unprivileged haifa-eval user exists..."
if ! id -u haifa-eval >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m -d /home/haifa-eval haifa-eval
fi
sudo mkdir -p /home/haifa-eval
sudo chown haifa-eval:haifa-eval /home/haifa-eval 2>/dev/null || true
sudo usermod -a -G haifa-eval "$EVAL_USER" || true
sudo usermod -a -G "$EVAL_USER" haifa-eval || true

echo "[bootstrap-harbor] Configuring standard directory hierarchy..."
sudo mkdir -p /opt/haifa-eval/bin
sudo mkdir -p /var/lib/haifa-eval/{runs,worktrees,evidence,facts,cache}
sudo chown -R haifa-eval:haifa-eval /var/lib/haifa-eval /opt/haifa-eval
sudo chmod -R 775 /var/lib/haifa-eval /opt/haifa-eval
sudo chmod g+s /var/lib/haifa-eval
sudo git config --system --add safe.directory '*' || true

if df -T /run 2>/dev/null | awk 'NR==2 {print $2}' | grep -qw "tmpfs"; then
  sudo mkdir -p /run/haifa-eval
  sudo chown haifa-eval:haifa-eval /run/haifa-eval
  sudo chmod 0700 /run/haifa-eval
else
  echo "[bootstrap-harbor] ERROR: /run is not a tmpfs filesystem"
  exit 1
fi

echo "[bootstrap-harbor] Installing standalone uv into /opt/haifa-eval/bin..."
UV_BIN="/opt/haifa-eval/bin/uv"
if [[ ! -x "$UV_BIN" ]]; then
  # GitHub release downloads are slow/unreliable from cn-north/cn-hangzhou
  # snapshots; install from the (Aliyun) PyPI mirror instead.
  UV_BIN_FALLBACK="$(command -v uv || true)"
  if [[ -n "$UV_BIN_FALLBACK" && "$UV_BIN_FALLBACK" != "/opt/haifa-eval/bin/uv" ]]; then
    echo "[bootstrap-harbor] Found preinstalled uv at $UV_BIN_FALLBACK"
  else
    sudo python3 -m venv /opt/haifa-eval/uv-venv
    sudo /opt/haifa-eval/uv-venv/bin/pip install --quiet \
      --index-url https://mirrors.aliyun.com/pypi/simple/ \
      --extra-index-url https://pypi.org/simple/ uv
    sudo mkdir -p /opt/haifa-eval/bin
    sudo ln -sf /opt/haifa-eval/uv-venv/bin/uv "$UV_BIN"
  fi
fi
sudo chown -R haifa-eval:haifa-eval /opt/haifa-eval/bin 2>/dev/null || true
if [[ ! -x "$UV_BIN" ]]; then
  echo "[bootstrap-harbor] ERROR: uv binary not installed at $UV_BIN"
  exit 1
fi

uv_version="$("$UV_BIN" --version 2>/dev/null || echo unavailable)"
docker_version="$(sudo docker --version 2>/dev/null || echo unavailable)"
compose_version="$(sudo docker compose version 2>/dev/null || echo unavailable)"

echo "[bootstrap-harbor] Exporting host facts..."
sudo mkdir -p "$FACTS_DIR"
cat /etc/os-release | jq -R -s 'split("\n") | map(select(length > 0) | split("=")) | map({(.[0]): .[1]}) | add' | sudo tee "$FACTS_DIR/os-release.json" >/dev/null || cp /etc/os-release "$FACTS_DIR/os-release.txt"
dpkg --print-architecture | jq -R '{architecture: .}' | sudo tee "$FACTS_DIR/architecture.json" >/dev/null || dpkg --print-architecture > "$FACTS_DIR/architecture.txt"

dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' "${PACKAGES[@]}" | sudo tee "$FACTS_DIR/installed-packages.tsv" >/dev/null

cat <<EOF | sudo tee "$FACTS_DIR/toolchain.json" >/dev/null
{
  "kind": "haifa-evals-harbor",
  "uvBinary": "/opt/haifa-eval/bin/uv",
  "uvVersion": "$uv_version",
  "dockerVersion": "$docker_version",
  "composeVersion": "$compose_version",
  "pythonVersion": "$(python3 --version 2>&1)"
}
EOF

echo "[bootstrap-harbor] Bootstrap complete."
