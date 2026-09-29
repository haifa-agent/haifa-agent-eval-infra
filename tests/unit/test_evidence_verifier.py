"""Tests for evidence manifest verification and credential leak scanning."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evalctl.core.errors import EvidenceError
from evalctl.evidence.verifier import (
    scan_for_secrets,
    verify_evidence_manifest,
    verify_ladder_report,
    verify_run_records,
    verify_secret_scan,
)


def test_verify_evidence_manifest_success(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    file1 = evidence_dir / "ladder-report.json"
    content1 = b'{"mode": "agent"}'
    file1.write_bytes(content1)
    sha1 = hashlib.sha256(content1).hexdigest()

    manifest_file = evidence_dir / "manifest.sha256"
    manifest_file.write_text(f"{sha1}  ladder-report.json\n", encoding="utf-8")

    verified = verify_evidence_manifest(evidence_dir)
    assert verified["ladder-report.json"] == sha1


def test_verify_evidence_manifest_detects_tampering(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    file1 = evidence_dir / "ladder-report.json"
    file1.write_bytes(b'{"mode": "agent"}')

    manifest_file = evidence_dir / "manifest.sha256"
    manifest_file.write_text(
        "0000000000000000000000000000000000000000000000000000000000000000  ladder-report.json\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="Integrity check failed"):
        verify_evidence_manifest(evidence_dir)


def test_scan_for_secrets_clean_and_violation(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "logs").mkdir()
    (evidence_dir / "logs" / "case.log").write_text("all good\n", encoding="utf-8")

    secret = "super-secret-value-123456"
    result = scan_for_secrets(evidence_dir, [secret])
    assert result["status"] == "CLEAN"
    assert verify_secret_scan(evidence_dir)["status"] == "CLEAN"

    (evidence_dir / "logs" / "case.log").write_text(
        f"leaked {secret}\n", encoding="utf-8"
    )
    result = scan_for_secrets(evidence_dir, [secret])
    assert result["status"] == "VIOLATION"
    assert "logs/case.log" in result["violations"][0]
    with pytest.raises(EvidenceError, match="INVALID_EVIDENCE: Secret scan revealed leaks"):
        verify_secret_scan(evidence_dir)


def test_verify_ladder_artifacts(tmp_path: Path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "ladder-report.json").write_text(
        json.dumps({"mode": "agent", "caseSet": "ladder-v1"}), encoding="utf-8"
    )
    (evidence_dir / "run-records.jsonl").write_text(
        json.dumps({"caseId": "L1-01", "accepted": True}) + "\n", encoding="utf-8"
    )

    report = verify_ladder_report(evidence_dir)
    assert report["caseSet"] == "ladder-v1"
    records = verify_run_records(evidence_dir)
    assert records[0]["caseId"] == "L1-01"


def test_pull_and_verify_evidence_blocks_tar_slip(tmp_path: Path):
    import io
    import tarfile
    from unittest.mock import MagicMock

    from evalctl.evidence.puller import pull_and_verify_evidence

    tar_bytes_io = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes_io, mode="w:gz") as tar:
        evil_data = b"malicious payload"
        ti = tarfile.TarInfo(name="../../evil.txt")
        ti.size = len(evil_data)
        tar.addfile(ti, io.BytesIO(evil_data))
    tar_bytes = tar_bytes_io.getvalue()

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
