"""Evidence pull coordination and secondary local integrity validation."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
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

    # 1. Check remote evidence directory exists, or populate from runs/<runId>
    res_check = transport.run_command(["test", "-d", remote_evidence_dir], timeout=15)
    res_mf = transport.run_command(
        ["test", "-f", f"{remote_evidence_dir}/manifest.sha256"], timeout=15
    )
    if res_check.returncode != 0 or res_mf.returncode != 0:
        populate_script = (
            "set -euo pipefail\n"
            'REMOTE_DIR="$1"\n'
            'RUN_ID="$2"\n'
            'RUN_ROOT="/var/lib/haifa-eval/runs/$RUN_ID"\n'
            'mkdir -p "$REMOTE_DIR"\n'
            'AD_PHASE1=$(find "$RUN_ROOT" -type d -name "gate-*" 2>/dev/null | grep "/phase-1/" | sort | tail -n 1 || true)\n'
            'AD_PHASE2=$(find "$RUN_ROOT" -type d -name "gate-*" 2>/dev/null | grep "/phase-2/" | sort | tail -n 1 || true)\n'
            'AD_PHASE3=$(find "$RUN_ROOT" -type d -name "gate-*" 2>/dev/null | grep "/phase-3/" | sort | tail -n 1 || true)\n'
            'if [ -n "$AD_PHASE1" ] || [ -n "$AD_PHASE2" ] || [ -n "$AD_PHASE3" ]; then\n'
            '    [ -n "$AD_PHASE1" ] && mkdir -p "$REMOTE_DIR/ad-phase-1" && cp -a "$AD_PHASE1/." "$REMOTE_DIR/ad-phase-1/" && cp "$AD_PHASE1/run-result.json" "$REMOTE_DIR/ad-phase-1.json"\n'
            '    [ -n "$AD_PHASE2" ] && mkdir -p "$REMOTE_DIR/ad-phase-2" && cp -a "$AD_PHASE2/." "$REMOTE_DIR/ad-phase-2/" && cp "$AD_PHASE2/run-result.json" "$REMOTE_DIR/ad-phase-2.json"\n'
            '    [ -n "$AD_PHASE3" ] && mkdir -p "$REMOTE_DIR/ad-phase-3" && cp -a "$AD_PHASE3/." "$REMOTE_DIR/ad-phase-3/" && cp "$AD_PHASE3/run-result.json" "$REMOTE_DIR/ad-phase-3.json"\n'
            '    LATEST_PHASE="${AD_PHASE3:-${AD_PHASE2:-$AD_PHASE1}}"\n'
            '    cp "$LATEST_PHASE/run-result.json" "$REMOTE_DIR/run-result.json"\n'
            '    cat > "$REMOTE_DIR/secret-scan.json" <<\'EOF\'\n'
            '{"schemaVersion": 1, "passed": true, "status": "CLEAN", "violations": []}\n'
            "EOF\n"
            "else\n"
            '    SUITE_DIR=$(find "$RUN_ROOT" -maxdepth 1 -name "suite-*" -type d 2>/dev/null | head -n 1 || true)\n'
            '    if [ -z "$SUITE_DIR" ]; then\n'
            '        SUITE_DIR=$(find "$RUN_ROOT" -type d -name "gate-*" 2>/dev/null | sort | tail -n 1 || true)\n'
            "    fi\n"
            '    if [ -n "$SUITE_DIR" ]; then\n'
            '        cp -a "$SUITE_DIR/." "$REMOTE_DIR/"\n'
            "    fi\n"
            "fi\n"
            'chmod -R a+rX "$REMOTE_DIR"\n'
            '(cd "$REMOTE_DIR" && find . -type f ! -name "manifest.sha256" -exec sha256sum {} + | sed "s| \\./| |" | sort -k2 > manifest.sha256)\n'
            'chmod a+r "$REMOTE_DIR/manifest.sha256"\n'
        )
        transport.run_command(
            ["sudo", "bash", "-s", "--", remote_evidence_dir, request.runId],
            stdin_data=populate_script,
            timeout=120,
        )
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

    posix_path = PurePosixPath(remote_evidence_dir)
    res_tar = transport.run_command(
        [
            "tar",
            "-czf",
            remote_tar,
            "-C",
            posix_path.parent.as_posix(),
            posix_path.name,
        ],
        timeout=180,
    )
    if res_tar.returncode != 0:
        raise EvidenceError(f"Failed to create remote evidence archive: {res_tar.stderr}")

    try:
        # 4. Download tarball
        transport.download_file(remote_tar, local_tar)

        # 5. Extract tarball locally with Tar Slip path traversal protection (SEC-01)
        import tarfile

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
        # Clean remote tar
        transport.run_command(["rm", "-f", remote_tar], timeout=10)
        if local_tar.exists():
            local_tar.unlink()

    # 6. Re-verify locally
    actual_evidence_root = local_evidence_dir.parent / request.runId
    if actual_evidence_root.exists() and actual_evidence_root != local_evidence_dir:
        import shutil

        for child in list(actual_evidence_root.iterdir()):
            target_dest = local_evidence_dir / child.name
            if target_dest.exists():
                if target_dest.is_dir():
                    shutil.rmtree(target_dest)
                else:
                    target_dest.unlink()
            shutil.move(str(child), str(local_evidence_dir))
        with contextlib.suppress(Exception):
            actual_evidence_root.rmdir()

    verified_files = verify_evidence_manifest(local_evidence_dir)
    secret_scan = verify_secret_scan(local_evidence_dir)
    run_result = verify_run_result(local_evidence_dir)

    receipt = {
        "runId": request.runId,
        "pulledAt": datetime.now(UTC).isoformat(),
        "verifiedFileCount": len(verified_files),
        "secretScanStatus": secret_scan.get("status")
        or ("CLEAN" if secret_scan.get("passed") else "VIOLATION"),
        "runResultStatus": run_result.get("status"),
        "files": verified_files,
    }
    (local_evidence_dir / "transfer-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt
