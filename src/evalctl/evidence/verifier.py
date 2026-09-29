"""Verification of the evidence root, manifest checksums, and credential leakage."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from evalctl.core.errors import EvidenceError

SECRET_SCAN_FILE = "secret-scan.json"
MANIFEST_FILE = "manifest.sha256"


def verify_evidence_manifest(evidence_dir: Path) -> dict[str, str]:
    """Verifies all files in an evidence directory against manifest.sha256."""
    manifest_file = evidence_dir / MANIFEST_FILE
    if not manifest_file.is_file():
        raise EvidenceError(f"Evidence directory missing {MANIFEST_FILE}: {evidence_dir}")

    verified_files: dict[str, str] = {}
    with manifest_file.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                raise EvidenceError(f"Invalid manifest line: '{line}'")
            expected_sha, rel_path = parts[0], parts[1].lstrip("*").strip()
            target_file = evidence_dir / rel_path
            if not target_file.is_file():
                raise EvidenceError(f"File listed in manifest does not exist: {rel_path}")

            digest = hashlib.sha256()
            with target_file.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_sha = digest.hexdigest()

            if actual_sha.lower() != expected_sha.lower():
                raise EvidenceError(
                    f"Integrity check failed for {rel_path}!\n"
                    f"  Expected: {expected_sha}\n"
                    f"  Actual:   {actual_sha}"
                )
            verified_files[rel_path] = actual_sha

    return verified_files


def scan_for_secrets(evidence_dir: Path, secret_values: list[str]) -> dict[str, Any]:
    """Scans pulled evidence for injected credential values and writes secret-scan.json.

    Only the file location is recorded in the report; the secret value itself is
    never written to disk or logs.
    """
    candidates = [v for v in secret_values if v and len(v) >= 8]
    violations: list[str] = []

    if candidates:
        for path in sorted(evidence_dir.rglob("*")):
            if not path.is_file() or path.name in (MANIFEST_FILE, SECRET_SCAN_FILE):
                continue
            try:
                content = path.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            rel = path.relative_to(evidence_dir).as_posix()
            for value in candidates:
                if value in content:
                    violations.append(f"credential value detected in {rel}")

    result = {
        "schemaVersion": 1,
        "status": "VIOLATION" if violations else "CLEAN",
        "scannedSecretCount": len(candidates),
        "violations": violations,
    }
    (evidence_dir / SECRET_SCAN_FILE).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def verify_secret_scan(evidence_dir: Path) -> dict[str, Any]:
    """Validates the locally produced secret-scan.json."""
    scan_file = evidence_dir / SECRET_SCAN_FILE
    if not scan_file.is_file():
        raise EvidenceError(f"Evidence directory missing {SECRET_SCAN_FILE}: {evidence_dir}")

    try:
        data = json.loads(scan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvidenceError(f"Failed to parse {SECRET_SCAN_FILE}: {exc}") from exc

    status = str(data.get("status", "")).upper()
    violations = data.get("violations", [])
    if status != "CLEAN" and violations:
        raise EvidenceError(
            f"INVALID_EVIDENCE: Secret scan revealed leaks or violations: {violations}"
        )
    return data


def verify_ladder_report(evidence_dir: Path) -> dict[str, Any]:
    """Validates presence and schema of ladder-report.json."""
    report_file = evidence_dir / "ladder-report.json"
    if not report_file.is_file():
        raise EvidenceError(f"Evidence directory missing ladder-report.json: {evidence_dir}")
    try:
        return json.loads(report_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvidenceError(f"Failed to parse ladder-report.json: {exc}") from exc


def verify_run_records(evidence_dir: Path) -> list[dict[str, Any]]:
    """Validates presence and line-by-line JSON of run-records.jsonl."""
    records_file = evidence_dir / "run-records.jsonl"
    if not records_file.is_file():
        raise EvidenceError(f"Evidence directory missing run-records.jsonl: {evidence_dir}")
    records: list[dict[str, Any]] = []
    with records_file.open("r", encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as exc:
                raise EvidenceError(f"Failed to parse run-records.jsonl line: {exc}") from exc
    return records


def collect_secret_values(request: Any) -> list[str]:
    """Collects injected credential values from the local environment for scanning."""
    values: list[str] = []
    for name in request.evaluation.requiredSecretEnvironmentNames:
        value = os.getenv(name)
        if value:
            values.append(value)
    return values
