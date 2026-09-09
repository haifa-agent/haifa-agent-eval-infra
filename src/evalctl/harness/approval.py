"""Budget and Plan Set human approval gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evalctl.core.errors import PlanApprovalError


def verify_and_record_approval(
    approved_plan_set_sha: str,
    local_plans_dir: Path,
    operator_id: str,
) -> dict[str, Any]:
    """Verifies that the operator-supplied approval digest matches plan-set.json."""
    plan_set_file = local_plans_dir / "plan-set.json"
    if not plan_set_file.is_file():
        raise PlanApprovalError(
            f"No plan-set.json found at {plan_set_file}; run 'evalctl plan' first"
        )

    try:
        plan_set = json.loads(plan_set_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PlanApprovalError(f"Failed to read plan-set.json: {exc}") from exc

    expected_sha = plan_set.get("planSetSha256", "")
    if approved_plan_set_sha.strip().lower() != expected_sha.strip().lower():
        raise PlanApprovalError(
            f"Approval Digest Mismatch!\n"
            f"  Approved by operator: {approved_plan_set_sha}\n"
            f"  Actual Plan Set:     {expected_sha}\n"
            f"FAIL-CLOSED: Execution aborted. Re-review the plan set before approving."
        )

    approval_record = {
        "operator": operator_id,
        "approvedPlanSetSha256": expected_sha,
        "approvedAt": datetime.now(UTC).isoformat(),
        "plans": plan_set.get("plans", []),
    }
    (local_plans_dir / "approval.json").write_text(
        json.dumps(approval_record, indent=2), encoding="utf-8"
    )
    return approval_record
