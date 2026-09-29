"""Deterministic evaluation report builder for the autonomous-delivery ladder."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.report.ladder import summarize_ladder


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with contextlib.suppress(Exception):
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _read_run_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(Exception):
            records.append(json.loads(line))
    return records


def build_evaluation_report(
    request: RunRequest,
    local_run_dir: Path,
) -> dict[str, Any]:
    """Generates a deterministic report from the ladder evidence artifacts."""
    evidence_dir = local_run_dir / "evidence"
    control_dir = local_run_dir / "control"

    # Credential leak scan gate
    scan_data = _read_json(evidence_dir / "secret-scan.json")
    scan_status = str(scan_data.get("status", "")).upper() if scan_data else ""
    is_valid_evidence = bool(scan_data) and not (
        scan_status != "CLEAN" and scan_data.get("violations")
    )

    # Source provenance
    repositories: dict[str, Any] = {}
    source_manifest = _read_json(control_dir / "source-manifest.json")
    if source_manifest:
        repositories = source_manifest.get("repositories", {})

    ladder_report = _read_json(evidence_dir / "ladder-report.json")
    records = _read_run_records(evidence_dir / "run-records.jsonl")
    usage_report = _read_json(evidence_dir / "usage-report.json")

    ladder_summary = None
    if ladder_report is not None or records:
        ladder_summary = summarize_ladder(ladder_report, records, usage_report)

    if not is_valid_evidence:
        top_status = "INVALID_EVIDENCE"
    elif ladder_report is None:
        top_status = "INCOMPLETE"
    else:
        top_status = "COMPLETE_PASS" if ladder_summary and ladder_summary["passed"] else (
            "COMPLETE_WITH_FAILURES"
        )

    report = {
        "schemaVersion": 2,
        "runId": request.runId,
        "status": top_status,
        "providerId": request.evaluation.providerId,
        "modelId": request.evaluation.modelId,
        "caseSet": request.evaluation.caseSet,
        "evaluatedAt": datetime.now(UTC).isoformat(),
        "repositories": repositories,
        "ladder": ladder_summary,
    }

    (local_run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    from evalctl.report.renderers import render_html, render_markdown

    (local_run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    (local_run_dir / "report.html").write_text(render_html(report), encoding="utf-8")

    return report
