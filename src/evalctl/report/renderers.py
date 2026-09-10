"""Report formatters for Terminal ANSI, JSON, and Markdown."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalctl.report.html_generator import generate_html_report


def render_json(report_data: dict[str, Any]) -> str:
    """Renders formatted JSON."""
    return json.dumps(report_data, indent=2, ensure_ascii=False)


def render_terminal(report_data: dict[str, Any]) -> str:
    """Renders ANSI colored terminal summary."""
    status = report_data.get("status", "UNKNOWN")
    color = "\033[92m" if "PASS" in status else "\033[91m"
    reset = "\033[0m"
    bold = "\033[1m"

    lines = [
        f"{bold}===================================================={reset}",
        f"{bold} HAIFA AGENT EVALUATION REPORT: {report_data.get('runId')}{reset}",
        f"{bold} Status: {color}{status}{reset}",
        f"{bold} Model:  {report_data.get('modelId')} ({report_data.get('providerId')}){reset}",
        f"{bold} Profile: {report_data.get('agentProfileRef')}{reset}",
        f"{bold}===================================================={reset}",
    ]

    cp = report_data.get("criticalPath")
    if cp:
        lines.append(f"\n{bold}[Critical Path]{reset}")
        lines.append(f"  Suite:    {cp.get('suiteId')} ({cp.get('role')})")
        lines.append(f"  Score:    {cp.get('coverage')}")
        lines.append(f"  Result:   {'PASS' if cp.get('passed') else 'FAIL'}")

    ad = report_data.get("autonomousDelivery")
    if ad:
        lines.append(f"\n{bold}[Autonomous Delivery]{reset}")
        lines.append(
            f"  Score:    {ad.get('combinedScore')} (Full 26: {ad.get('hasFull26Coverage')})"
        )
        lines.append(f"  Result:   {'PASS' if ad.get('passed') else 'FAIL'}")
        agg = ad.get("aggregates", {})
        cost_sym = "¥" if report_data.get("providerId") == "zhipu" else "$"
        cost_code = "CNY" if report_data.get("providerId") == "zhipu" else "USD"
        lines.append(
            f"  Metrics:  Tokens in/out: {agg.get('inputTokens')}/{agg.get('outputTokens')} | "
            f"Est. Cost: {cost_sym}{agg.get('estimatedCostUsd')} {cost_code}"
        )

    lines.append(f"{bold}===================================================={reset}\n")
    return "\n".join(lines)


def render_markdown(report_data: dict[str, Any]) -> str:
    """Renders a comprehensive GitHub Flavored Markdown report."""
    run_id = report_data.get("runId", "")
    status = report_data.get("status", "")
    provider_id = report_data.get("providerId", "")
    model_id = report_data.get("modelId", "")
    profile = report_data.get("agentProfileRef", "")

    md = [
        f"# Haifa Agent Evaluation Report: `{run_id}`\n",
        f"- **Status**: `{status}`",
        f"- **Provider**: `{provider_id}`",
        f"- **Model**: `{model_id}`",
        f"- **Agent Profile**: `{profile}`",
        f"- **Evaluated At**: {report_data.get('evaluatedAt', '')}\n",
        "## Source Commits",
        "| Repository | Commit SHA |",
        "| --- | --- |",
    ]

    repos = report_data.get("repositories", {})
    for repo_name, repo_info in repos.items():
        md.append(f"| `{repo_name}` | `{repo_info.get('commit', '')}` |")

    cp = report_data.get("criticalPath")
    if cp:
        md.append("\n## Critical Path Evaluation")
        md.append(f"- **Suite**: `{cp.get('suiteId')}`")
        md.append(f"- **Role**: `{cp.get('role')}`")
        md.append(f"- **Coverage**: `{cp.get('coverage')}`")
        md.append(f"- **Status**: `{'PASS' if cp.get('passed') else 'FAIL'}`\n")
        md.append("| Case ID | Repetition | Status | Failure Reason |")
        md.append("| --- | --- | --- | --- |")
        for c in cp.get("cases", []):
            md.append(
                f"| `{c.get('caseId')}` | {c.get('repetition')} | `{c.get('status')}` | {c.get('failureReason') or '-'} |"
            )

    ad = report_data.get("autonomousDelivery")
    if ad:
        md.append("\n## Autonomous Delivery Evaluation")
        md.append(f"- **Combined Score**: `{ad.get('combinedScore')}`")
        md.append(f"- **Full 26 Case Coverage**: `{ad.get('hasFull26Coverage')}`")
        md.append(f"- **Status**: `{'PASS' if ad.get('passed') else 'FAIL'}`\n")

        agg = ad.get("aggregates", {})
        md.append("### Resource & Cost Aggregates")
        md.append(f"- **Input Tokens**: {agg.get('inputTokens'):,}")
        md.append(f"- **Output Tokens**: {agg.get('outputTokens'):,}")
        md.append(f"- **Model Calls**: {agg.get('modelCalls')}")
        md.append(f"- **Tool Calls**: {agg.get('toolCalls')}")
        md.append(f"- **Total Duration**: {agg.get('totalDurationSeconds')}s")
        cost_sym = "¥" if report_data.get("providerId") == "zhipu" else "$"
        cost_code = "CNY" if report_data.get("providerId") == "zhipu" else "USD"
        md.append(
            f"- **Estimated Cost**: {cost_sym}{agg.get('estimatedCostUsd')} {cost_code} (Known: {agg.get('providerReportedCostKnown')})\n"
        )

        md.append("### Phase Breakdown")
        md.append("| Phase | Evaluated | Passed | Status |")
        md.append("| --- | --- | --- | --- |")
        for pname, pinfo in ad.get("phases", {}).items():
            md.append(
                f"| `{pname}` | {pinfo.get('evaluated')} | {pinfo.get('passed')} | `{pinfo.get('status')}` |"
            )

        if ad.get("cases"):
            md.append("\n### Case Details")
            md.append(
                "| Phase | Case ID | Repetition | Gate | Hidden Acceptance | Native Status |"
            )
            md.append("| --- | --- | --- | --- | --- | --- |")
            for c in ad.get("cases", []):
                gate_str = "PASS" if c.get("gatePassed") else "FAIL"
                acc_str = "PASS" if c.get("hiddenAcceptance") else "FAIL"
                md.append(
                    f"| `{c.get('phase')}` | `{c.get('caseId')}` | {c.get('repetition')} | `{gate_str}` | `{acc_str}` | `{c.get('nativeStatus')}` |"
                )

    return "\n".join(md)


def render_html(report_data: dict[str, Any], local_run_dir: Path) -> str:
    """Renders interactive self-contained HTML report."""
    return generate_html_report(report_data, local_run_dir)
