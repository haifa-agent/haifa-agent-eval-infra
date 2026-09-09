#!/usr/bin/env bash
# Haifa Agent Remote Doctor (Read-Only Host Preflight)
set -euo pipefail

output_json() {
  local os_id os_version arch sudo_ok disk_free_gb run_tmpfs github_ok maven_ok
  
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    os_id="${ID:-unknown}"
    os_version="${VERSION_ID:-unknown}"
  else
    os_id="unknown"
    os_version="unknown"
  fi

  arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"

  if sudo -n true 2>/dev/null; then
    sudo_ok=true
  else
    sudo_ok=false
  fi

  # Disk free in GB on /var/lib or /
  local target_dir="/var/lib"
  [[ -d "$target_dir" ]] || target_dir="/"
  disk_free_gb="$(df -BG "$target_dir" | awk 'NR==2 {gsub("G",""); print $4}')"

  # Check /run tmpfs
  if df -T /run 2>/dev/null | awk 'NR==2 {print $2}' | grep -qw "tmpfs"; then
    run_tmpfs=true
  else
    run_tmpfs=false
  fi

  # Network check (timeout 5s)
  if curl -s -m 5 -I https://github.com >/dev/null 2>&1; then
    github_ok=true
  else
    github_ok=false
  fi

  if curl -s -m 5 -I https://repo1.maven.org >/dev/null 2>&1; then
    maven_ok=true
  else
    maven_ok=false
  fi

  cat <<EOF
{
  "os": {
    "id": "$os_id",
    "version": "$os_version"
  },
  "architecture": "$arch",
  "hasPasswordlessSudo": $sudo_ok,
  "diskFreeGb": ${disk_free_gb:-0},
  "isRunTmpfs": $run_tmpfs,
  "network": {
    "githubHttpsOk": $github_ok,
    "mavenHttpsOk": $maven_ok
  },
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
}

output_json
