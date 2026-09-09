"""Verification of evidence root, manifest checksums, and secret scans."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evalctl.core.errors import EvidenceError


def verify_evidence_manifest(evidence_dir: Path) -> dict[str, str]:
    """Verifies all files in an evidence directory against manifest.sha256."""
    manifest_file = evidence_dir / "manifest.sha256"
    if not manifest_file.is_file():
        raise EvidenceError(f"Evidence directory missing manifest.sha256: {evidence_dir}")

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

            # Compute SHA
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


def verify_secret_scan(evidence_dir: Path) -> dict[str, Any]:
    """Validates secret-scan.json within the evidence root."""
    scan_file = evidence_dir / "secret-scan.json"
    if not scan_file.is_file():
        raise EvidenceError(f"Evidence directory missing secret-scan.json: {evidence_dir}")

    try:
        data = json.loads(scan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvidenceError(f"Failed to parse secret-scan.json: {exc}") from exc

    status = data.get("status", "").upper()
    violations = data.get("violations", [])
    if status != "CLEAN" and violations:
        raise EvidenceError(
            f"INVALID_EVIDENCE: Secret scan revealed leaks or violations: {violations}"
        )
    return data


def verify_run_result(evidence_dir: Path) -> dict[str, Any]:
    """Validates presence and schema of run-result.json."""
    result_file = evidence_dir / "run-result.json"
    if not result_file.is_file():
        raise EvidenceError(f"Evidence directory missing run-result.json: {evidence_dir}")

    try:
        return json.loads(result_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise EvidenceError(f"Failed to parse run-result.json: {exc}") from exc
