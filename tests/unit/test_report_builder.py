"""Tests for the deterministic ladder report builder and renderers."""

from __future__ import annotations

import json
from pathlib import Path

from evalctl.config.loader import load_run_request
from evalctl.report.builder import build_evaluation_report
from evalctl.report.renderers import render_json, render_markdown, render_terminal


def _write_evidence(run_dir: Path, records: list[dict], scan_status: str = "CLEAN") -> None:
    evidence_dir = run_dir / "evidence"
    control_dir = run_dir / "control"
    evidence_dir.mkdir(parents=True)
    control_dir.mkdir(parents=True)

    (evidence_dir / "secret-scan.json").write_text(
        json.dumps({"status": scan_status, "violations": [] if scan_status == "CLEAN" else ["x"]}),
        encoding="utf-8",
    )
    ladder_report = {
        "schemaVersion": 1,
        "mode": "agent",
        "caseSet": "ladder-v1",
        "repeat": 1,
        "levels": {"L1": {"cases": 2, "runs": len(records), "passedRuns": sum(1 for r in records if r.get("accepted"))}},
        "evaluation": {"mode": "agent", "model": "glm-5.3-flash", "caseSet": "ladder-v1"},
    }
    (evidence_dir / "ladder-report.json").write_text(json.dumps(ladder_report), encoding="utf-8")
    (evidence_dir / "run-records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
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


def _record(case_id: str, accepted: bool) -> dict:
    return {
        "caseId": case_id,
        "level": "L1",
        "attempt": 1,
        "status": "PASSED" if accepted else "FAILED",
        "accepted": accepted,
        "expected": accepted,
        "durationMillis": 1000,
        "agentDurationMillis": 900,
        "agentExitCode": 0,
        "checks": {"functional.a": accepted},
        "failures": [] if accepted else ["functional.a: assertion failed"],
        "contractProblems": [],
    }


def test_build_evaluation_report_pass(sample_request_path: Path, tmp_path: Path):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    _write_evidence(run_dir, [_record("L1-01", True), _record("L1-02", True)])

    report = build_evaluation_report(req, run_dir)
    assert report["status"] == "COMPLETE_PASS"
    assert report["ladder"]["score"] == "2/2"
    assert report["ladder"]["passed"] is True
    assert report["caseSet"] == "ladder-v1"

    term_out = render_terminal(report)
    assert "COMPLETE_PASS" in term_out
    assert "L1" in term_out

    md_out = render_markdown(report)
    assert "# Haifa Agent Ladder Report" in md_out
    assert "`L1-01`" in md_out

    json_out = render_json(report)
    assert "COMPLETE_PASS" in json_out

    assert (run_dir / "report.html").is_file()


def test_build_evaluation_report_secret_scan_failed_marks_invalid(
    sample_request_path: Path, tmp_path: Path
):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    _write_evidence(run_dir, [_record("L1-01", True)], scan_status="VIOLATION")

    report = build_evaluation_report(req, run_dir)
    assert report["status"] == "INVALID_EVIDENCE"


def test_build_evaluation_report_with_failures(sample_request_path: Path, tmp_path: Path):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    _write_evidence(run_dir, [_record("L1-01", True), _record("L1-02", False)])

    report = build_evaluation_report(req, run_dir)
    assert report["status"] == "COMPLETE_WITH_FAILURES"
    assert report["ladder"]["score"] == "1/2"
    assert report["ladder"]["passed"] is False
    assert report["ladder"]["cases"][1]["failures"] == ["functional.a: assertion failed"]
