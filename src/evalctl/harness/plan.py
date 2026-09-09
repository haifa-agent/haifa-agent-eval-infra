"""Harness plan execution and Plan Set compilation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalctl.config.loader import calculate_sha256, canonical_json
from evalctl.config.schema import RunRequest
from evalctl.core.errors import PlanApprovalError
from evalctl.transport.ssh import SSHTransport


def generate_plan_set(
    transport: SSHTransport,
    request: RunRequest,
    request_sha256: str,
    local_plans_dir: Path,
    verbose: bool = False,
) -> dict[str, Any]:
    """Runs harness plan for all configured suites and compiles canonical Plan Set."""
    local_plans_dir.mkdir(parents=True, exist_ok=True)
    worktree = f"/var/lib/haifa-eval/worktrees/{request.runId}/haifa-agent"
    remote_plans_dir = f"/var/lib/haifa-eval/plans/{request.runId}"
    transport.run_command(["mkdir", "-p", remote_plans_dir])

    plan_entries: list[dict[str, Any]] = []

    for suite_run in request.evaluation.runs:
        remote_plan_out = f"{remote_plans_dir}/{suite_run.id}.json"
        run_root = f"/var/lib/haifa-eval/runs/{request.runId}"
        cmd = [
            "bash",
            f"{worktree}/test-config/scripts/run-suite.sh",
            "plan",
            "--suite",
            suite_run.suite,
            "--profile",
            request.evaluation.agentProfileRef,
            "--platform",
            suite_run.platform,
            "--mode",
            "live",
            "--run-root",
            run_root,
            "--output",
            remote_plan_out,
            "--project-root",
            worktree,
            "--config-root",
            f"{worktree}/test-config",
        ]
        res = transport.run_command(cmd, timeout=600, verbose=verbose)
        if res.returncode != 0:
            raise PlanApprovalError(
                f"Harness plan failed for suite '{suite_run.suite}' ({res.returncode}):\n{res.stderr.strip()}"
            )

        # Pull plan output to local
        res_cat = transport.run_command(["cat", remote_plan_out], timeout=15)
        if res_cat.returncode != 0:
            raise PlanApprovalError(f"Failed to read generated plan {remote_plan_out}")

        plan_content_str = res_cat.stdout.strip()
        local_plan_file = local_plans_dir / f"{suite_run.id}.json"
        local_plan_file.write_text(plan_content_str, encoding="utf-8")

        try:
            plan_obj = json.loads(plan_content_str)
        except Exception as exc:
            raise PlanApprovalError(
                f"Generated plan {suite_run.id}.json is invalid JSON: {exc}"
            ) from exc

        # Extract budget and verify runner
        plan_sha = (
            plan_obj.get("plan", {}).get("sha256")
            or plan_obj.get("sha256")
            or calculate_sha256(canonical_json(plan_obj))
        )
        plan_content = plan_obj.get("plan", {}).get("content", {})
        budget_info = plan_content.get("budget", {})
        budget_val = str(budget_info.get("limit", suite_run.approveBudget))
        budget_unit = budget_info.get("unit", "USD")

        plan_entries.append(
            {
                "runEntryId": suite_run.id,
                "suiteId": suite_run.suite,
                "planSha256": plan_sha,
                "budgetUnit": budget_unit,
                "budget": budget_val,
            }
        )

    # Assemble canonical Plan Set
    plan_set_raw = {
        "schemaVersion": 1,
        "runId": request.runId,
        "requestSha256": request_sha256,
        "plans": plan_entries,
    }
    plan_set_sha256 = calculate_sha256(canonical_json(plan_set_raw))
    plan_set_data = {
        **plan_set_raw,
        "planSetSha256": plan_set_sha256,
    }

    (local_plans_dir / "plan-set.json").write_text(
        json.dumps(plan_set_data, indent=2), encoding="utf-8"
    )
    return plan_set_data
