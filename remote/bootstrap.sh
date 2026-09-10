#!/usr/bin/env bash
# Haifa Agent Remote Host Bootstrap
set -euo pipefail

FACTS_DIR="/var/lib/haifa-eval/facts"
EVAL_USER="${1:-$USER}"
PACKAGES=(
  ca-certificates curl wget git openssh-client
  jq tar unzip zip xz-utils rsync
  openjdk-21-jdk-headless maven build-essential
  python3 python3-venv python3-pip
  nodejs npm golang-go
  procps psmisc lsof acl util-linux locales tzdata
)

echo "[bootstrap] Checking passwordless sudo..."
sudo -n true || { echo "[bootstrap] ERROR: passwordless sudo required"; exit 1; }

echo "[bootstrap] Updating APT package index..."
sudo apt-get update -y

echo "[bootstrap] Installing required baseline packages..."
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${PACKAGES[@]}"

echo "[bootstrap] Verifying JDK 21 architecture-independently..."
eval_java="$(readlink -f "$(command -v java)")"
eval_javac="$(readlink -f "$(command -v javac)")"
eval_java_home="$(dirname "$(dirname "$eval_java")")"

if [[ "$eval_java_home" != "$(dirname "$(dirname "$eval_javac")")" ]]; then
  echo "[bootstrap] ERROR: java and javac belong to different JDK installations"
  exit 1
fi

if [[ ! -x "$eval_java_home/bin/java" || ! -x "$eval_java_home/bin/javac" ]]; then
  echo "[bootstrap] ERROR: java or javac binary is not executable at $eval_java_home"
  exit 1
fi

java_version="$("$eval_java" -version 2>&1 | awk -F '"' '/version/ {print $2}')"
echo "[bootstrap] Found Java version: $java_version at $eval_java_home"

echo "[bootstrap] Ensuring dedicated unprivileged haifa-eval user exists..."
if ! id -u haifa-eval >/dev/null 2>&1; then
  sudo useradd -r -s /bin/bash -m -d /home/haifa-eval haifa-eval
fi
sudo usermod -a -G haifa-eval "$EVAL_USER" || true
sudo usermod -a -G "$EVAL_USER" haifa-eval || true

echo "[bootstrap] Configuring standard directory hierarchy for haifa-eval and user $EVAL_USER..."
sudo mkdir -p /opt/haifa-eval
sudo mkdir -p /var/lib/haifa-eval/{runs,worktrees,plans,evidence,facts}
sudo chown -R haifa-eval:haifa-eval /var/lib/haifa-eval
sudo chmod -R 775 /var/lib/haifa-eval
sudo chmod g+s /var/lib/haifa-eval
sudo chown -R haifa-eval:haifa-eval /opt/haifa-eval
sudo git config --system --add safe.directory '*' || true

if df -T /run 2>/dev/null | awk 'NR==2 {print $2}' | grep -qw "tmpfs"; then
  sudo mkdir -p /run/haifa-eval
  sudo chown haifa-eval:haifa-eval /run/haifa-eval
  sudo chmod 0700 /run/haifa-eval
else
  echo "[bootstrap] ERROR: /run is not a tmpfs filesystem"
  exit 1
fi

echo "[bootstrap] Exporting host facts..."
sudo mkdir -p "$FACTS_DIR"
cat /etc/os-release | jq -R -s 'split("\n") | map(select(length > 0) | split("=")) | map({(.[0]): .[1]}) | add' | sudo tee "$FACTS_DIR/os-release.json" >/dev/null || cp /etc/os-release "$FACTS_DIR/os-release.txt"
dpkg --print-architecture | jq -R '{architecture: .}' | sudo tee "$FACTS_DIR/architecture.json" >/dev/null || dpkg --print-architecture > "$FACTS_DIR/architecture.txt"

dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' "${PACKAGES[@]}" | sudo tee "$FACTS_DIR/installed-packages.tsv" >/dev/null

cat <<EOF | sudo tee "$FACTS_DIR/toolchain.json" >/dev/null
{
  "javaHome": "$eval_java_home",
  "javaVersion": "$java_version",
  "pythonVersion": "$(python3 --version 2>&1)",
  "nodeVersion": "$(node --version 2>&1)",
  "npmVersion": "$(npm --version 2>&1)",
  "goVersion": "$(go version 2>&1)",
  "gitVersion": "$(git --version 2>&1)"
}
EOF

sudo chown -R "$EVAL_USER:$EVAL_USER" "$FACTS_DIR"
echo "[bootstrap] Host bootstrap completed successfully."
