"""Remote host bootstrap orchestration and verification."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import BootstrapError
from evalctl.transport.ssh import SSHTransport


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Extracts numeric tuple (major, minor, patch) from version string."""
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if not match:
        return (0, 0, 0)
    major, minor = int(match.group(1)), int(match.group(2))
    patch = int(match.group(3)) if match.group(3) else 0
    return (major, minor, patch)


def run_host_bootstrap(
    transport: SSHTransport,
    request: RunRequest,
    local_bootstrap_script: Path,
    lockfile_path: Path,
    local_facts_dir: Path,
) -> dict[str, Any]:
    """Uploads and runs remote bootstrap script, then pulls and validates toolchain facts."""
    lock_data = json.loads(lockfile_path.read_text(encoding="utf-8"))

    # Upload bootstrap script to remote
    script_content = local_bootstrap_script.read_text(encoding="utf-8")
    res = transport.run_command(
        ["sudo", "bash", "-s"],
        stdin_data=script_content,
        timeout=600,
    )
    if res.returncode != 0:
        raise BootstrapError(
            f"Host bootstrap script failed ({res.returncode}):\n{res.stderr.strip()}"
        )

    # Pull facts directory
    local_facts_dir.mkdir(parents=True, exist_ok=True)
    res_facts = transport.run_command(
        ["cat", "/var/lib/haifa-eval/facts/toolchain.json"], timeout=15
    )
    if res_facts.returncode != 0:
        raise BootstrapError(f"Failed to read toolchain.json from remote: {res_facts.stderr}")

    try:
        toolchain = json.loads(res_facts.stdout.strip())
    except Exception as exc:
        raise BootstrapError(f"Failed to parse toolchain.json: {exc}") from exc

    (local_facts_dir / "toolchain.json").write_text(
        json.dumps(toolchain, indent=2), encoding="utf-8"
    )

    # Validate toolchain against lockfile
    toolchain_locks = lock_data.get("toolchain", {})
    java_lock = toolchain_locks.get("java", {})
    if java_lock.get("majorVersion") == 21:
        java_ver = toolchain.get("javaVersion", "")
        if not java_ver.startswith("21.") and not java_ver.startswith("21-"):
            raise BootstrapError(f"Java version mismatch: expected major 21, got: {java_ver}")

    # Validate Python
    py_lock = toolchain_locks.get("python", {})
    min_py = parse_semver(py_lock.get("minVersion", "3.11.0"))
    actual_py = parse_semver(toolchain.get("pythonVersion", ""))
    if actual_py < min_py:
        raise BootstrapError(f"Python version too low: got {actual_py}, minimum {min_py}")

    return toolchain
