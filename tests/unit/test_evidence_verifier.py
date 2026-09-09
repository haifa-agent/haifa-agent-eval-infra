"""Tests for evidence manifest verification and secret scan checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evalctl.core.errors import EvidenceError
from evalctl.evidence.verifier import (
    verify_evidence_manifest,
    verify_secret_scan,
)


def test_verify_evidence_manifest_success(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    file1 = evidence_dir / "run-result.json"
    content1 = b'{"status": "PASS"}'
    file1.write_bytes(content1)
    sha1 = hashlib.sha256(content1).hexdigest()

    manifest_file = evidence_dir / "manifest.sha256"
    manifest_file.write_text(f"{sha1}  run-result.json\n", encoding="utf-8")

    verified = verify_evidence_manifest(evidence_dir)
    assert verified["run-result.json"] == sha1


def test_verify_evidence_manifest_detects_tampering(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    file1 = evidence_dir / "run-result.json"
    file1.write_bytes(b'{"status": "PASS"}')

    manifest_file = evidence_dir / "manifest.sha256"
    manifest_file.write_text(
        "0000000000000000000000000000000000000000000000000000000000000000  run-result.json\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="Integrity check failed"):
        verify_evidence_manifest(evidence_dir)


def test_secret_scan_violations_raise_error(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    scan_file = evidence_dir / "secret-scan.json"
    scan_file.write_text(
        json.dumps(
            {
                "status": "VIOLATION",
                "violations": ["API_KEY_LEAK in logs/agent.log"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="INVALID_EVIDENCE: Secret scan revealed leaks"):
        verify_secret_scan(evidence_dir)


def test_pull_and_verify_evidence_blocks_tar_slip(tmp_path: Path):
    import io
    import tarfile
    from unittest.mock import MagicMock

    from evalctl.evidence.puller import pull_and_verify_evidence

    # Create a malicious tarball with ../../evil.txt
    tar_bytes_io = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes_io, mode="w:gz") as tar:
        evil_data = b"malicious payload"
        ti = tarfile.TarInfo(name="../../evil.txt")
        ti.size = len(evil_data)
        tar.addfile(ti, io.BytesIO(evil_data))
    tar_bytes = tar_bytes_io.getvalue()

    # Mock transport
    transport = MagicMock()
    transport.run_command.return_value.returncode = 0
    transport.run_command.return_value.stdout = ""
    transport.run_command.return_value.stderr = ""

    def mock_download(remote_path, local_path):
        Path(local_path).write_bytes(tar_bytes)

    transport.download_file.side_effect = mock_download

    mock_request = MagicMock()
    mock_request.runId = "test-run-001"
    mock_request.output.remoteEvidenceRoot = "/var/lib/haifa-eval/evidence"

    local_evidence_dir = tmp_path / "test-run-001" / "evidence"

    with pytest.raises(EvidenceError, match="Malicious archive member outside target directory"):
        pull_and_verify_evidence(transport, mock_request, local_evidence_dir)
