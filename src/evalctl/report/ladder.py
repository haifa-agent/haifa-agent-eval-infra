"""Deterministic projection of autonomous-delivery ladder evidence."""

from __future__ import annotations

from typing import Any


def _case_summary(record: dict[str, Any]) -> dict[str, Any]:
    checks = record.get("checks")
    checks_passed = sum(1 for v in checks.values() if v) if isinstance(checks, dict) else 0
    checks_total = len(checks) if isinstance(checks, dict) else 0
    failures = record.get("failures") or []
    return {
        "caseId": record.get("caseId"),
        "level": record.get("level"),
        "tier": record.get("tier"),
        "attempt": record.get("attempt", 1),
        "status": record.get("status"),
        "accepted": bool(record.get("accepted")),
        "expected": record.get("expected"),
        "durationMillis": record.get("durationMillis", 0),
        "agentDurationMillis": record.get("agentDurationMillis", 0),
        "agentExitCode": record.get("agentExitCode"),
        "checksPassed": checks_passed,
        "checksTotal": checks_total,
        "failures": list(failures),
        "contractProblems": record.get("contractProblems") or [],
    }


def summarize_ladder(
    ladder_report: dict[str, Any] | None,
    records: list[dict[str, Any]],
    usage_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Builds a deterministic ladder summary from runner artifacts."""
    report = ladder_report or {}
    total = len(records)
    passed = sum(1 for r in records if r.get("accepted"))
    failed = sum(1 for r in records if str(r.get("status", "")).upper() == "FAILED")
    incomplete = sum(
        1 for r in records if str(r.get("status", "")).upper() == "INCOMPLETE_BUDGET"
    )

    status_counts: dict[str, int] = {}
    for record in records:
        key = str(record.get("status", "UNKNOWN"))
        status_counts[key] = status_counts.get(key, 0) + 1

    evaluation = report.get("evaluation", {}) if isinstance(report, dict) else {}
    usage_totals = usage_report.get("totals") if isinstance(usage_report, dict) else None

    return {
        "mode": report.get("mode"),
        "caseSet": report.get("caseSet"),
        "repeat": report.get("repeat"),
        "totalRuns": total,
        "passedRuns": passed,
        "failedRuns": failed,
        "incompleteBudgetRuns": incomplete,
        "passRate": round(passed / total, 4) if total else 0.0,
        "score": f"{passed}/{total}",
        "passed": total > 0 and passed == total,
        "statusCounts": status_counts,
        "levels": report.get("levels", {}),
        "tiers": report.get("tiers", {}),
        "cases": [_case_summary(r) for r in records],
        "evaluation": evaluation,
        "usageTotals": usage_totals,
    }
