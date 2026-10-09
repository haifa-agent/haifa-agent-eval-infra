"""Remote host preflight inspection (doctor)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import HostDoctorError
from evalctl.transport.ssh import SSHTransport


def run_host_doctor(
    transport: SSHTransport,
    request: RunRequest,
    local_doctor_script: Path,
) -> dict[str, Any]:
    """Executes read-only doctor checks on the remote host and validates results."""
    script_content = local_doctor_script.read_text(encoding="utf-8")

    # Execute doctor script via bash stdin (no files modified on remote)
    res = transport.run_command(["/bin/bash", "-s"], stdin_data=script_content, timeout=30)
    if res.returncode != 0:
        raise HostDoctorError(
            f"Doctor script execution failed ({res.returncode}): {res.stderr.strip()}"
        )

    try:
        report = json.loads(res.stdout.strip())
    except Exception as exc:
        raise HostDoctorError(
            f"Failed to parse doctor report JSON: {exc}\nOutput was:\n{res.stdout}"
        ) from exc

    # Enforce checks
    failures: list[str] = []

    if request.target.requirePasswordlessSudo and not report.get("hasPasswordlessSudo"):
        failures.append("Passwordless sudo is required but not configured for target user")

    if not report.get("isRunTmpfs"):
        failures.append("/run mount point is NOT tmpfs (required for safe secret boundary)")

    disk_free = report.get("diskFreeGb", 0)
    if disk_free < 20:
        failures.append(f"Insufficient disk space: {disk_free}GB free, at least 20GB required")

    net = report.get("network", {})
    if not net.get("githubHttpsOk"):
        failures.append("Remote host cannot reach https://github.com")

    is_harbor = request.evaluation.kind == "haifa-evals-harbor"

    if is_harbor:
        if not report.get("dockerComposeOk"):
            failures.append(
                "Docker Engine / Compose v2 unavailable to remote "
                "(required for kind: haifa-evals-harbor)"
            )
        if not report.get("uvOk"):
            failures.append("uv is not installed on the remote host (required for evals)")
    else:
        if not net.get("mavenHttpsOk"):
            failures.append("Remote host cannot reach https://repo1.maven.org")

    if is_harbor and not net.get("bigmodelHttpsOk"):
        failures.append("Remote host cannot reach the GLM provider endpoint (open.bigmodel.cn)")

    if failures:
        msg = "\n  - ".join(["Host preflight doctor checks FAILED:"] + failures)
        raise HostDoctorError(msg)

    return report
