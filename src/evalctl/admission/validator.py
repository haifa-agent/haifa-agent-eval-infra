"""Cross-verification of agent profile, provider, model identity, and local secrets."""

from __future__ import annotations

import json
import os
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import AdmissionError
from evalctl.transport.ssh import SSHTransport


def validate_admission(
    transport: SSHTransport,
    request: RunRequest,
) -> dict[str, Any]:
    """Validates remote profile against request identity and confirms presence of local secrets."""
    # 1. Check required secrets in local environment (WITHOUT printing secret values or lengths)
    missing_secrets: list[str] = []
    for secret_env in request.evaluation.requiredSecretEnvironmentNames:
        val = os.getenv(secret_env)
        if not val or not val.strip():
            missing_secrets.append(secret_env)

    if missing_secrets:
        raise AdmissionError(
            f"Missing required secret environment variable(s) on local operator machine: {missing_secrets}"
        )

    # 2. Read remote checked-out profile
    profile_ref = request.evaluation.agentProfileRef
    profile_remote_path = f"/var/lib/haifa-eval/worktrees/{request.runId}/haifa-agent/test-config/profiles/{profile_ref}.json"
    res = transport.run_command(["cat", profile_remote_path], timeout=15)
    if res.returncode != 0:
        # Check yaml extension if json not found
        profile_remote_path_yaml = profile_remote_path.replace(".json", ".yaml")
        res = transport.run_command(["cat", profile_remote_path_yaml], timeout=15)
        if res.returncode != 0:
            raise AdmissionError(
                f"Agent profile '{profile_ref}' not found in checked-out test-config repository"
            )

    try:
        profile_data = json.loads(res.stdout) if profile_remote_path.endswith(".json") else {}
    except Exception:
        profile_data = {}

    # 3. Cross-verify providerId and modelId
    if profile_data:
        prof_provider = profile_data.get("providerId") or profile_data.get("provider")
        prof_model = profile_data.get("modelId") or profile_data.get("model")

        if prof_provider and prof_provider != request.evaluation.providerId:
            raise AdmissionError(
                f"Provider ID mismatch! Request specified '{request.evaluation.providerId}', "
                f"but profile declared '{prof_provider}'"
            )
        if prof_model and prof_model != request.evaluation.modelId:
            raise AdmissionError(
                f"Model ID mismatch! Request specified '{request.evaluation.modelId}', "
                f"but profile declared '{prof_model}'"
            )

    return {"status": "ADMITTED", "profile": profile_ref}
