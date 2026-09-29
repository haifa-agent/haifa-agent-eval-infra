"""Source code checkout and verification for the product repository."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import SourcePrepareError
from evalctl.transport.ssh import SSHTransport


def prepare_sources(
    transport: SSHTransport,
    request: RunRequest,
    local_source_script: Path,
    local_control_dir: Path,
    verbose: bool = False,
) -> dict[str, Any]:
    """Transfers temporary deploy key, runs source preparation, and verifies the commit."""
    key_env = request.source.githubPrivateKeyFileEnv
    key_path_str = os.getenv(key_env)
    if not key_path_str:
        raise SourcePrepareError(f"GitHub deploy key env var '{key_env}' is not set")
    key_file = Path(key_path_str.strip().strip("\"'")).resolve()
    if not key_file.is_file():
        raise SourcePrepareError(f"GitHub deploy key file not found: {key_file}")

    key_content = key_file.read_text(encoding="utf-8")
    remote_key_path = f"/tmp/haifa-eval-gh-{request.runId}.key"

    res_key = transport.run_command(
        ["bash", "-c", f"cat > {remote_key_path} && chmod 0600 {remote_key_path}"],
        stdin_data=key_content,
        timeout=15,
    )
    if res_key.returncode != 0:
        raise SourcePrepareError(f"Failed to inject temporary GitHub key: {res_key.stderr}")

    product = request.source.product
    try:
        script_content = local_source_script.read_text(encoding="utf-8")
        args = [
            "bash",
            "-s",
            "--",
            request.runId,
            product.url,
            product.target_ref,
            remote_key_path,
        ]
        res_prep = transport.run_command(
            args, stdin_data=script_content, timeout=600, verbose=verbose
        )
        if res_prep.returncode != 0:
            raise SourcePrepareError(
                f"Source preparation failed ({res_prep.returncode}):\n{res_prep.stderr}"
            )

        remote_manifest_path = (
            f"/var/lib/haifa-eval/worktrees/{request.runId}/source-manifest.json"
        )
        res_man = transport.run_command(["cat", remote_manifest_path], timeout=15)
        if res_man.returncode != 0:
            raise SourcePrepareError(f"Failed to read source manifest: {res_man.stderr}")

        manifest = json.loads(res_man.stdout.strip())
        local_control_dir.mkdir(parents=True, exist_ok=True)
        (local_control_dir / "source-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        man_repos = manifest.get("repositories", {})
        resolved = man_repos.get("product", {}).get("commit", "")
        if product.commit and resolved != product.commit:
            raise SourcePrepareError(
                f"Product commit mismatch in source manifest: expected {product.commit}, got {resolved}"
            )
        if not product.commit:
            product.commit = resolved

        return manifest
    finally:
        transport.run_command(["rm", "-f", remote_key_path], timeout=10)
