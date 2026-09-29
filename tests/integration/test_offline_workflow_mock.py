"""Integration test simulating the full offline workflow with mocks."""

from __future__ import annotations

import json
from pathlib import Path

from evalctl.cli import main
from evalctl.config.loader import load_run_request
from evalctl.core.lifecycle import LifecycleManager, LifecycleStage


def test_cli_request_validate(sample_request_path: Path):
    ret = main(["request", "validate", "--file", str(sample_request_path)])
    assert ret == 0


def test_full_lifecycle_simulation(sample_request_path: Path, tmp_path: Path):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    control_dir = run_dir / "control"
    evidence_dir = run_dir / "evidence"
    control_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)

    lifecycle = LifecycleManager(req.runId, control_dir)

    lifecycle.record(LifecycleStage.REQUEST_VALIDATED)
    lifecycle.record(LifecycleStage.HOST_TRUSTED, extra={"hostKeySha256": req.target.hostKeySha256})
    lifecycle.record(
        LifecycleStage.HOST_PREFLIGHTED, extra={"hasPasswordlessSudo": True, "diskFreeGb": 50}
    )
    lifecycle.record(LifecycleStage.BOOTSTRAPPED, extra={"javaVersion": "21.0.2"})
    lifecycle.record(
        LifecycleStage.SOURCE_PINNED,
        artifacts={"repositories": {"product": {"commit": "0123456789abcdef0123456789abcdef01234567"}}},
    )
    lifecycle.record(LifecycleStage.AGENT_BUILT)
    lifecycle.record(LifecycleStage.RUNNING)

    (evidence_dir / "secret-scan.json").write_text(
        json.dumps({"status": "CLEAN"}), encoding="utf-8"
    )
    (evidence_dir / "ladder-report.json").write_text(
        json.dumps({"mode": "agent", "caseSet": "ladder-v1", "levels": {}}), encoding="utf-8"
    )
    (evidence_dir / "run-records.jsonl").write_text(
        json.dumps({"caseId": "L1-01", "level": "L1", "status": "PASSED", "accepted": True})
        + "\n",
        encoding="utf-8",
    )
    (control_dir / "source-manifest.json").write_text(
        json.dumps({"repositories": {"product": {"commit": "0123456789abcdef0123456789abcdef01234567"}}}),
        encoding="utf-8",
    )
    lifecycle.record(LifecycleStage.EVIDENCE_READY)
    lifecycle.record(LifecycleStage.EVIDENCE_PULLED)

    from evalctl.report.builder import build_evaluation_report

    report = build_evaluation_report(req, run_dir)
    lifecycle.record(LifecycleStage.REPORT_READY, extra={"status": report["status"]})
    lifecycle.record(LifecycleStage.COMPLETE)

    assert report["status"] == "COMPLETE_PASS"
    assert lifecycle.latest_stage() == "COMPLETE"
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "report.md").is_file()
