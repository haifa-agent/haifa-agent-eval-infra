"""Projection and metrics aggregation for Critical Path evaluations."""

from __future__ import annotations

from typing import Any


def summarize_critical_path(run_result_data: dict[str, Any]) -> dict[str, Any]:
    """Extracts deterministic Critical Path metrics (Smoke vs CP-01~CP-11)."""
    suite_id = run_result_data.get("suiteId", "")
    cases_raw = run_result_data.get("cases", [])

    is_smoke = "smoke" in suite_id.lower()
    total_cases = len(cases_raw)
    passed_cases = sum(1 for c in cases_raw if c.get("status") in ("PASS", "PASSED", "SUCCESS"))
    failed_cases = sum(1 for c in cases_raw if c.get("status") not in ("PASS", "PASSED", "SUCCESS"))

    case_details: list[dict[str, Any]] = []
    for c in cases_raw:
        case_details.append(
            {
                "caseId": c.get("id"),
                "repetition": c.get("repetition", 1),
                "status": c.get("status", "UNKNOWN"),
                "failureReason": c.get("failureReason") or c.get("error"),
                "durationMs": c.get("durationMs", 0),
            }
        )

    summary = {
        "suiteId": suite_id,
        "isSmoke": is_smoke,
        "role": "admission" if is_smoke else "formal",
        "totalCases": total_cases,
        "passedCases": passed_cases,
        "failedCases": failed_cases,
        "coverage": f"{passed_cases}/{total_cases}" if total_cases > 0 else "0/0",
        "passed": (failed_cases == 0 and total_cases > 0),
        "cases": case_details,
        "stability": {
            "processTreeNaturalExit": run_result_data.get("processTreeNaturalExit", True),
            "repositoryStateStable": run_result_data.get("repositoryStateStable", True),
        },
    }
    return summary
