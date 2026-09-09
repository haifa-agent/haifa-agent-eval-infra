"""Deterministic evaluation report builder."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.report.autonomous_delivery import summarize_autonomous_delivery
from evalctl.report.critical_path import summarize_critical_path


def build_evaluation_report(
    request: RunRequest,
    local_run_dir: Path,
) -> dict[str, Any]:
    """Generates a complete, deterministic report from authoritative evidence JSONs."""
    evidence_dir = local_run_dir / "evidence"
    control_dir = local_run_dir / "control"

    # Check secret scan
    secret_scan_file = evidence_dir / "secret-scan.json"
    is_valid_evidence = True
    if secret_scan_file.is_file():
        try:
            scan_data = json.loads(secret_scan_file.read_text(encoding="utf-8"))
            if scan_data.get("status", "").upper() != "CLEAN" and scan_data.get("violations"):
                is_valid_evidence = False
        except Exception:
            is_valid_evidence = False
    else:
        is_valid_evidence = False

    # Read source manifest
    source_manifest_file = control_dir / "source-manifest.json"
    repositories = {}
    if source_manifest_file.is_file():
        with contextlib.suppress(Exception):
            manifest = json.loads(source_manifest_file.read_text(encoding="utf-8"))
            repositories = manifest.get("repositories", {})

    # Read run results
    run_result_file = evidence_dir / "run-result.json"
    run_result_data: dict[str, Any] = {}
    if run_result_file.is_file():
        with contextlib.suppress(Exception):
            run_result_data = json.loads(run_result_file.read_text(encoding="utf-8"))

    # Build sub-reports
    cp_summary = None
    ad_summary = None

    if "cases" in run_result_data:
        # Check if it's CP or AD
        suite_id = run_result_data.get("suiteId", "")
        if "autonomous" in suite_id.lower() or "ad-" in suite_id.lower():
            ad_summary = summarize_autonomous_delivery([run_result_data])
        else:
            cp_summary = summarize_critical_path(run_result_data)

    # Check multi-phase AD files in evidence
    ad_phase_files = list(evidence_dir.glob("ad-phase-*.json"))
    if ad_phase_files:
        phase_results = []
        for pf in sorted(ad_phase_files):
            with contextlib.suppress(Exception):
                phase_results.append(json.loads(pf.read_text(encoding="utf-8")))
        if phase_results:
            ad_summary = summarize_autonomous_delivery(phase_results)

    # Determine overall status
    if not is_valid_evidence:
        top_status = "INVALID_EVIDENCE"
    elif not run_result_data:
        top_status = "INCOMPLETE"
    else:
        cp_pass = cp_summary.get("passed", True) if cp_summary else True
        ad_pass = ad_summary.get("passed", True) if ad_summary else True
        top_status = "COMPLETE_PASS" if cp_pass and ad_pass else "COMPLETE_WITH_FAILURES"

    report = {
        "schemaVersion": 1,
        "runId": request.runId,
        "status": top_status,
        "providerId": request.evaluation.providerId,
        "modelId": request.evaluation.modelId,
        "agentProfileRef": request.evaluation.agentProfileRef,
        "evaluatedAt": datetime.now(UTC).isoformat(),
        "repositories": repositories,
        "criticalPath": cp_summary,
        "autonomousDelivery": ad_summary,
    }

    # Persist report.json and report.md
    (local_run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    from evalctl.report.renderers import render_markdown

    (local_run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")

    return report
