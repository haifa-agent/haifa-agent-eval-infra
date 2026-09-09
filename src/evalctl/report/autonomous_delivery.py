"""Projection and metrics aggregation for Autonomous Delivery (26 cases)."""

from __future__ import annotations

from typing import Any


def summarize_autonomous_delivery(phase_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Extracts deterministic Autonomous Delivery metrics across Phase 1/2/3."""
    phases_summary: dict[str, Any] = {}
    all_cases: list[dict[str, Any]] = []

    total_evaluated = 0
    total_passed = 0

    total_input_tokens = 0
    total_output_tokens = 0
    total_model_calls = 0
    total_tool_calls = 0
    total_duration_ms = 0
    total_estimated_cost = 0.0
    cost_known = True

    for phase_data in phase_results:
        phase_name = phase_data.get("phase", phase_data.get("suiteId", "unknown"))
        cases = phase_data.get("cases", [])
        p_evaluated = len(cases)
        p_passed = sum(1 for c in cases if c.get("gatePassed", False) or c.get("status") == "PASS")

        phases_summary[phase_name] = {
            "evaluated": p_evaluated,
            "passed": p_passed,
            "status": "PASS" if p_passed == p_evaluated and p_evaluated > 0 else "FAIL",
        }

        total_evaluated += p_evaluated
        total_passed += p_passed

        for c in cases:
            all_cases.append(
                {
                    "caseId": c.get("id"),
                    "repetition": c.get("repetition", 1),
                    "phase": phase_name,
                    "gatePassed": c.get("gatePassed", False),
                    "nativeStatus": c.get("nativeStatus", c.get("status")),
                    "hiddenAcceptance": c.get("hiddenAcceptance", False),
                    "failureClassification": c.get("failureClassification"),
                }
            )

            metrics = c.get("metrics", {})
            total_input_tokens += metrics.get("inputTokens", 0)
            total_output_tokens += metrics.get("outputTokens", 0)
            total_model_calls += metrics.get("modelCalls", 0)
            total_tool_calls += metrics.get("toolCalls", 0)
            total_duration_ms += c.get("durationMs", 0)
            if "estimatedCost" in metrics:
                total_estimated_cost += float(metrics.get("estimatedCost", 0.0))
            else:
                cost_known = False

    # Check complete 26 cases coverage
    has_full_26 = total_evaluated == 26
    combined_pass = (total_passed == 26) if has_full_26 else False

    return {
        "hasFull26Coverage": has_full_26,
        "combinedScore": f"{total_passed}/{total_evaluated}",
        "passed": combined_pass,
        "phases": phases_summary,
        "cases": all_cases,
        "aggregates": {
            "inputTokens": total_input_tokens,
            "outputTokens": total_output_tokens,
            "modelCalls": total_model_calls,
            "toolCalls": total_tool_calls,
            "totalDurationSeconds": round(total_duration_ms / 1000.0, 2),
            "estimatedCostUsd": round(total_estimated_cost, 4),
            "providerReportedCostKnown": cost_known,
        },
    }
