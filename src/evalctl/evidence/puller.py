"""Evidence pull coordination and secondary local integrity validation."""

from __future__ import annotations

import contextlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import EvidenceError
from evalctl.evidence.verifier import (
    collect_secret_values,
    scan_for_secrets,
    verify_evidence_manifest,
    verify_ladder_report,
    verify_run_records,
    verify_secret_scan,
)
from evalctl.transport.ssh import SSHTransport

MANIFEST_GEN_SCRIPT = """set -euo pipefail
REMOTE_DIR="$1"
if [ -d "$REMOTE_DIR" ]; then
  chmod -R u+rwX "$REMOTE_DIR" 2>/dev/null || true
  (cd "$REMOTE_DIR" && find . -type f ! -name manifest.sha256 \
      -exec sha256sum {} + | sed "s| \\./| |" | sort -k2 > manifest.sha256)
  chmod -R a+rX "$REMOTE_DIR" 2>/dev/null || true
  chmod a+r "$REMOTE_DIR/manifest.sha256" 2>/dev/null || true
fi
"""


def pull_and_verify_evidence(
    transport: SSHTransport,
    request: RunRequest,
    local_evidence_dir: Path,
) -> dict[str, Any]:
    """Pulls the ladder evidence root and validates manifest, scan, and artifacts."""
    remote_evidence_dir = f"{request.output.remoteEvidenceRoot}/{request.runId}"

    res_check = transport.run_command(["test", "-d", remote_evidence_dir], timeout=15)
    if res_check.returncode != 0:
        raise EvidenceError(f"Remote evidence directory not found: {remote_evidence_dir}")

    # Generate the remote manifest over the ladder artifacts before transfer.
    transport.run_command(
        ["sudo", "bash", "-s", "--", remote_evidence_dir],
        stdin_data=MANIFEST_GEN_SCRIPT,
        timeout=180,
    )

    res_mf = transport.run_command(
        ["test", "-f", f"{remote_evidence_dir}/manifest.sha256"], timeout=15
    )
    if res_mf.returncode != 0:
        raise EvidenceError(f"Remote manifest.sha256 missing in {remote_evidence_dir}")

    local_evidence_dir.mkdir(parents=True, exist_ok=True)
    remote_tar = f"/tmp/evidence-{request.runId}.tar.gz"
    local_tar = local_evidence_dir.parent / f"evidence-{request.runId}.tar.gz"

    posix_path = PurePosixPath(remote_evidence_dir)
    res_tar = transport.run_command(
        ["tar", "-czf", remote_tar, "-C", posix_path.parent.as_posix(), posix_path.name],
        timeout=300,
    )
    if res_tar.returncode != 0:
        raise EvidenceError(f"Failed to create remote evidence archive: {res_tar.stderr}")

    try:
        transport.download_file(remote_tar, local_tar)

        target_base = local_evidence_dir.parent.resolve()
        with tarfile.open(local_tar, "r:gz") as tar:
            for member in tar.getmembers():
                dest_path = (target_base / member.name).resolve()
                if not dest_path.is_relative_to(target_base):
                    raise EvidenceError(
                        f"Malicious archive member outside target directory: {member.name}"
                    )
            if hasattr(tarfile, "data_filter"):
                tar.extractall(path=target_base, filter="data")
            else:
                tar.extractall(path=target_base)
    finally:
        transport.run_command(["rm", "-f", remote_tar], timeout=10)
        if local_tar.exists():
            local_tar.unlink()

    # Flatten extracted <runId>/ contents into local_evidence_dir if needed.
    actual_root = local_evidence_dir.parent / request.runId
    if actual_root.exists() and actual_root.resolve() != local_evidence_dir.resolve():
        for child in list(actual_root.iterdir()):
            dest = local_evidence_dir / child.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(child), str(local_evidence_dir))
        with contextlib.suppress(Exception):
            actual_root.rmdir()

    verified_files = verify_evidence_manifest(local_evidence_dir)

    # Local credential-leak scan over the pulled evidence.
    secret_values = collect_secret_values(request)
    secret_scan = scan_for_secrets(local_evidence_dir, secret_values)
    verify_secret_scan(local_evidence_dir)

    ladder_report = verify_ladder_report(local_evidence_dir)
    records = verify_run_records(local_evidence_dir)

    evaluation = ladder_report.get("evaluation", {}) if isinstance(ladder_report, dict) else {}
    receipt = {
        "runId": request.runId,
        "pulledAt": datetime.now(UTC).isoformat(),
        "verifiedFileCount": len(verified_files),
        "secretScanStatus": secret_scan.get("status"),
        "ladderStatus": ladder_report.get("mode") if isinstance(ladder_report, dict) else None,
        "evaluatedRuns": len(records),
        "files": verified_files,
        "evaluation": evaluation,
    }
    (local_evidence_dir / "transfer-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt
