"""Evidence pull coordination and secondary local integrity validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import EvidenceError
from evalctl.evidence.verifier import (
    verify_evidence_manifest,
    verify_run_result,
    verify_secret_scan,
)
from evalctl.transport.ssh import SSHTransport


def pull_and_verify_evidence(
    transport: SSHTransport,
    request: RunRequest,
    local_evidence_dir: Path,
) -> dict[str, Any]:
    """Pulls remote evidence via archive/SCP and validates manifest and secret scan."""
    remote_evidence_dir = f"{request.output.remoteEvidenceRoot}/{request.runId}"

    # 1. Check remote evidence directory exists
    res_check = transport.run_command(["test", "-d", remote_evidence_dir], timeout=15)
    if res_check.returncode != 0:
        raise EvidenceError(f"Remote evidence directory not found: {remote_evidence_dir}")

    # 2. Check remote manifest exists
    res_mf = transport.run_command(
        ["test", "-f", f"{remote_evidence_dir}/manifest.sha256"], timeout=15
    )
    if res_mf.returncode != 0:
        raise EvidenceError(f"Remote manifest.sha256 missing in {remote_evidence_dir}")

    # 3. Create a tarball on remote for atomic transfer
    local_evidence_dir.mkdir(parents=True, exist_ok=True)
    remote_tar = f"/tmp/evidence-{request.runId}.tar.gz"
    local_tar = local_evidence_dir.parent / f"evidence-{request.runId}.tar.gz"

    res_tar = transport.run_command(
        [
            "tar",
            "-czf",
            remote_tar,
            "-C",
            str(Path(remote_evidence_dir).parent),
            Path(remote_evidence_dir).name,
        ],
        timeout=180,
    )
    if res_tar.returncode != 0:
        raise EvidenceError(f"Failed to create remote evidence archive: {res_tar.stderr}")

    try:
        # 4. Download tarball
        transport.download_file(remote_tar, local_tar)

        # 5. Extract tarball locally
        import tarfile

        with tarfile.open(local_tar, "r:gz") as tar:
            tar.extractall(path=local_evidence_dir.parent)
    finally:
        # Clean remote tar
        transport.run_command(["rm", "-f", remote_tar], timeout=10)
        if local_tar.exists():
            local_tar.unlink()

    # 6. Re-verify locally
    actual_evidence_root = local_evidence_dir.parent / request.runId
    if actual_evidence_root.exists() and actual_evidence_root != local_evidence_dir:
        # Move or rename if needed
        import shutil

        if local_evidence_dir.exists():
            shutil.rmtree(local_evidence_dir)
        actual_evidence_root.rename(local_evidence_dir)

    verified_files = verify_evidence_manifest(local_evidence_dir)
    secret_scan = verify_secret_scan(local_evidence_dir)
    run_result = verify_run_result(local_evidence_dir)

    receipt = {
        "runId": request.runId,
        "pulledAt": datetime.now(UTC).isoformat(),
        "verifiedFileCount": len(verified_files),
        "secretScanStatus": secret_scan.get("status"),
        "runResultStatus": run_result.get("status"),
        "files": verified_files,
    }
    (local_evidence_dir / "transfer-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt
