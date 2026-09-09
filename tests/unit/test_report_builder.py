"""Tests for deterministic report builder and renderers."""

from __future__ import annotations

import json
from pathlib import Path

from evalctl.config.loader import load_run_request
from evalctl.report.builder import build_evaluation_report
from evalctl.report.renderers import render_json, render_markdown, render_terminal


def test_build_evaluation_report_cp_pass(sample_request_path: Path, tmp_path: Path):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    evidence_dir = run_dir / "evidence"
    control_dir = run_dir / "control"
    evidence_dir.mkdir(parents=True)
    control_dir.mkdir(parents=True)

    # Mock secret-scan.json
    (evidence_dir / "secret-scan.json").write_text(
        json.dumps({"status": "CLEAN"}), encoding="utf-8"
    )

    # Mock run-result.json with Critical Path results
    run_result = {
        "suiteId": "critical-path-regression-v1",
        "cases": [
            {"id": "CP-01", "status": "PASS", "repetition": 1},
            {"id": "CP-02", "status": "PASS", "repetition": 1},
        ],
        "processTreeNaturalExit": True,
        "repositoryStateStable": True,
    }
    (evidence_dir / "run-result.json").write_text(json.dumps(run_result), encoding="utf-8")

    # Mock source-manifest.json
    (control_dir / "source-manifest.json").write_text(
        json.dumps(
            {
                "repositories": {
                    "product": {"commit": "0123456789abcdef0123456789abcdef01234567"},
                }
            }
        ),
        encoding="utf-8",
    )

    report = build_evaluation_report(req, run_dir)
    assert report["status"] == "COMPLETE_PASS"
    assert report["criticalPath"]["coverage"] == "2/2"
    assert report["criticalPath"]["passed"] is True

    term_out = render_terminal(report)
    assert "COMPLETE_PASS" in term_out
    assert "CP-01" not in term_out or "Critical Path" in term_out

    md_out = render_markdown(report)
    assert "# Haifa Agent Evaluation Report" in md_out
    assert "| `CP-01` | 1 | `PASS` | - |" in md_out

    json_out = render_json(report)
    assert "COMPLETE_PASS" in json_out


def test_build_evaluation_report_secret_scan_failed_marks_invalid_evidence(
    sample_request_path: Path, tmp_path: Path
):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True)

    # Bad secret scan
    (evidence_dir / "secret-scan.json").write_text(
        json.dumps({"status": "VIOLATION", "violations": ["API_KEY"]}), encoding="utf-8"
    )
    (evidence_dir / "run-result.json").write_text(
        json.dumps({"cases": [{"id": "CP-01", "status": "PASS"}]}), encoding="utf-8"
    )

    report = build_evaluation_report(req, run_dir)
    assert report["status"] == "INVALID_EVIDENCE"
