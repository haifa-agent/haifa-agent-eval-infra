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
        phase_name = (
            phase_data.get("phase")
            or phase_data.get("nativeResult", {}).get("phase")
            or phase_data.get("suiteId")
            or phase_data.get("nativeResult", {}).get("suiteId")
            or "unknown"
        )
        cases = (
            phase_data.get("cases")
            or phase_data.get("nativeResult", {}).get("results")
            or []
        )
        p_evaluated = len(cases)
        p_passed = sum(
            1
            for c in cases
            if c.get("gatePassed") is True
            or str(c.get("status", "")).upper() in ("PASS", "PASSED")
            or str(c.get("nativeStatus", "")).upper() in ("PASS", "PASSED", "GATE_PASSED")
        )

        phases_summary[phase_name] = {
            "evaluated": p_evaluated,
            "passed": p_passed,
            "status": "PASS" if p_passed == p_evaluated and p_evaluated > 0 else "FAIL",
        }

        total_evaluated += p_evaluated
        total_passed += p_passed

        for c in cases:
            gate_passed = (
                c.get("gatePassed") is True
                or str(c.get("status", "")).upper() in ("PASS", "PASSED")
                or str(c.get("nativeStatus", "")).upper() in ("PASS", "PASSED", "GATE_PASSED")
            )
            hidden_acc = (
                c.get("acceptancePassed")
                if "acceptancePassed" in c
                else c.get("hiddenAcceptance", False)
            )

            all_cases.append(
                {
                    "caseId": c.get("caseId") or c.get("id"),
                    "repetition": c.get("repetition", 1),
                    "phase": phase_name,
                    "gatePassed": gate_passed,
                    "nativeStatus": c.get("nativeStatus", c.get("status")),
                    "hiddenAcceptance": hidden_acc,
                    "failureClassification": c.get("failureClassification")
                    or phase_data.get("failureClassification"),
                }
            )

            metrics = c.get("metrics", {})
            in_tok = c.get("inputTokens") or metrics.get("inputTokens", 0)
            out_tok = c.get("outputTokens") or metrics.get("outputTokens", 0)
            mc = c.get("modelCalls") or metrics.get("modelCalls", 0)
            tc = c.get("toolCalls") or metrics.get("toolCalls", 0)

            dur_ms = 0
            if "wallTimeSeconds" in c:
                dur_ms = int(float(c["wallTimeSeconds"]) * 1000)
            elif "durationMs" in c:
                dur_ms = c["durationMs"]
            elif "durationMs" in metrics:
                dur_ms = metrics["durationMs"]

            total_input_tokens += in_tok
            total_output_tokens += out_tok
            total_model_calls += mc
            total_tool_calls += tc
            total_duration_ms += dur_ms

            if "estimatedCost" in metrics:
                total_estimated_cost += float(metrics.get("estimatedCost", 0.0))
            elif "estimatedCostMinorUnits" not in phase_data.get("usageSummary", {}):
                cost_known = False

    if total_estimated_cost == 0.0:
        total_minor_units = sum(
            phase_data.get("usageSummary", {}).get("estimatedCostMinorUnits", 0)
            for phase_data in phase_results
        )
        if total_minor_units > 0:
            total_estimated_cost = round(total_minor_units / 100.0, 2)
            cost_known = any(
                phase_data.get("usageSummary", {}).get("providerReportedCostKnown", False)
                for phase_data in phase_results
            )

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
