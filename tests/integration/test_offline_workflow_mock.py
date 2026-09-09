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
    req, _, req_sha = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    run_dir = tmp_path / req.runId
    control_dir = run_dir / "control"
    evidence_dir = run_dir / "evidence"
    plans_dir = run_dir / "plans"
    control_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)
    plans_dir.mkdir(parents=True)

    lifecycle = LifecycleManager(req.runId, control_dir)

    # 1. Validation stage
    lifecycle.record(LifecycleStage.REQUEST_VALIDATED)

    # 2. Host trusted
    lifecycle.record(LifecycleStage.HOST_TRUSTED, extra={"hostKeySha256": req.target.hostKeySha256})

    # 3. Host preflighted
    lifecycle.record(
        LifecycleStage.HOST_PREFLIGHTED, extra={"hasPasswordlessSudo": True, "diskFreeGb": 50}
    )

    # 4. Bootstrapped
    lifecycle.record(LifecycleStage.BOOTSTRAPPED, extra={"javaVersion": "21.0.2"})

    # 5. Source pinned
    lifecycle.record(
        LifecycleStage.SOURCE_PINNED,
        artifacts={"repositories": {"product": req.source.repositories.product.commit}},
    )

    # 6. Plan created
    plan_set = {
        "schemaVersion": 1,
        "runId": req.runId,
        "planSetSha256": "mock-digest-123456",
        "plans": [{"runEntryId": "cp-smoke", "budget": "5"}],
    }
    (plans_dir / "plan-set.json").write_text(json.dumps(plan_set), encoding="utf-8")
    lifecycle.record(LifecycleStage.PLAN_CREATED, artifacts={"planSetSha256": "mock-digest-123456"})
    lifecycle.record(LifecycleStage.WAITING_APPROVAL)

    assert lifecycle.latest_stage() == "WAITING_APPROVAL"

    # 7. Running
    lifecycle.record(LifecycleStage.RUNNING, extra={"approvedPlanSet": "mock-digest-123456"})

    # 8. Evidence ready & pulled
    (evidence_dir / "secret-scan.json").write_text(
        json.dumps({"status": "CLEAN"}), encoding="utf-8"
    )
    (evidence_dir / "run-result.json").write_text(
        json.dumps(
            {
                "suiteId": "critical-path-regression-v1",
                "cases": [{"id": "CP-01", "status": "PASS"}],
            }
        ),
        encoding="utf-8",
    )
    lifecycle.record(LifecycleStage.EVIDENCE_READY)
    lifecycle.record(LifecycleStage.EVIDENCE_PULLED)

    # 9. Report
    from evalctl.report.builder import build_evaluation_report

    report = build_evaluation_report(req, run_dir)
    lifecycle.record(LifecycleStage.REPORT_READY, extra={"status": report["status"]})
    lifecycle.record(LifecycleStage.COMPLETE)

    assert lifecycle.latest_stage() == "COMPLETE"
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "report.md").is_file()
