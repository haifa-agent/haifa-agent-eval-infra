"""Report formatters for Terminal ANSI, JSON, Markdown, and HTML."""

from __future__ import annotations

import html
import json
from typing import Any


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
        f"{bold} HAIFA AGENT LADDER REPORT: {report_data.get('runId')}{reset}",
        f"{bold} Status: {color}{status}{reset}",
        f"{bold} Model:  {report_data.get('modelId')} ({report_data.get('providerId')}){reset}",
        f"{bold} Case Set: {report_data.get('caseSet')}{reset}",
        f"{bold}===================================================={reset}",
    ]

    ladder = report_data.get("ladder")
    if ladder:
        lines.append(f"\n{bold}[Autonomous Delivery Ladder]{reset}")
        lines.append(f"  Mode:     {ladder.get('mode')}")
        lines.append(f"  Score:    {ladder.get('score')} ({ladder.get('passRate')})")
        lines.append(f"  Result:   {'PASS' if ladder.get('passed') else 'FAIL'}")
        counts = ladder.get("statusCounts", {})
        if counts:
            lines.append(
                "  Runs:     "
                + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            )
        levels = ladder.get("levels", {})
        for level_name, info in sorted(levels.items()):
            lines.append(
                f"    {level_name}: passed {info.get('passedRuns')}/{info.get('runs')}"
            )
    usage = ladder.get("usageTotals")
    if usage:
        lines.append(f"  Usage:    {json.dumps(usage, ensure_ascii=False)}")

    harbor = report_data.get("harbor")
    if harbor:
        lines.append(f"\n{bold}[Harbor Terminal-Bench Eval]{reset}")
        lines.append(f"  Eval Id:  {harbor.get('evalId')}")
        lines.append(f"  Score:    {harbor.get('score')} ({harbor.get('passRate')})")
        lines.append(f"  Result:   {'PASS' if harbor.get('passed') else 'FAIL'}")
        for candidate, info in sorted((harbor.get("perCandidate") or {}).items()):
            lines.append(
                f"    {candidate}: passed {info.get('passed')}/{info.get('attempts')}"
            )

    lines.append(f"{bold}===================================================={reset}\n")
    return "\n".join(lines)


def render_markdown(report_data: dict[str, Any]) -> str:
    """Renders a comprehensive GitHub Flavored Markdown report."""
    run_id = report_data.get("runId", "")
    status = report_data.get("status", "")

    md = [
        f"# Haifa Agent Ladder Report: `{run_id}`\n",
        f"- **Status**: `{status}`",
        f"- **Provider**: `{report_data.get('providerId')}`",
        f"- **Model**: `{report_data.get('modelId')}`",
        f"- **Case Set**: `{report_data.get('caseSet')}`",
        f"- **Evaluated At**: {report_data.get('evaluatedAt', '')}\n",
        "## Source Commits",
        "| Repository | Commit SHA |",
        "| --- | --- |",
    ]

    repos = report_data.get("repositories", {})
    for repo_name, repo_info in repos.items():
        commit = repo_info.get("commit", "") if isinstance(repo_info, dict) else repo_info
        md.append(f"| `{repo_name}` | `{commit}` |")

    ladder = report_data.get("ladder")
    if ladder:
        md.append("\n## Autonomous Delivery Ladder")
        md.append(f"- **Mode**: `{ladder.get('mode')}`")
        md.append(f"- **Score**: `{ladder.get('score')}`")
        md.append(f"- **Pass Rate**: `{ladder.get('passRate')}`")
        md.append(f"- **Status**: `{'PASS' if ladder.get('passed') else 'FAIL'}`\n")

        levels = ladder.get("levels", {})
        if levels:
            md.append("### Level Breakdown")
            md.append("| Level | Passed | Runs |")
            md.append("| --- | --- | --- |")
            for level_name, info in sorted(levels.items()):
                md.append(
                    f"| `{level_name}` | {info.get('passedRuns')} | {info.get('runs')} |"
                )
            md.append("")

        if ladder.get("cases"):
            md.append("### Case Results")
            md.append(
                "| Case | Level | Attempt | Status | Checks | Agent Exit | Duration (s) |"
            )
            md.append("| --- | --- | --- | --- | --- | --- | --- |")
            for c in ladder.get("cases", []):
                duration = (c.get("durationMillis") or 0) / 1000.0
                md.append(
                    f"| `{c.get('caseId')}` | `{c.get('level')}` | {c.get('attempt')} | "
                    f"`{c.get('status')}` | {c.get('checksPassed')}/{c.get('checksTotal')} | "
                    f"{c.get('agentExitCode')} | {duration:.1f} |"
                )

        usage = ladder.get("usageTotals")
        if usage:
            md.append("\n### Resource Usage")
            for key, value in sorted(usage.items()):
                md.append(f"- **{key}**: {value}")

    harbor = report_data.get("harbor")
    if harbor:
        md.append("\n## Harbor Terminal-Bench Eval")
        md.append(f"- **Eval Id**: `{harbor.get('evalId')}`")
        md.append(f"- **Score**: `{harbor.get('score')}`")
        md.append(f"- **Pass Rate**: `{harbor.get('passRate')}`")
        md.append(f"- **Status**: `{'PASS' if harbor.get('passed') else 'FAIL'}`\n")
        per_candidate = harbor.get("perCandidate") or {}
        if per_candidate:
            md.append("### Per Candidate")
            md.append("| Candidate | Passed | Attempts |")
            md.append("| --- | --- | --- |")
            for candidate, info in sorted(per_candidate.items()):
                md.append(
                    f"| `{candidate}` | {info.get('passed')} | {info.get('attempts')} |"
                )
            md.append("")
        failures = harbor.get("failures") or []
        if failures:
            md.append("### Task Failures")
            md.append("| Task | Candidate | Reward | Failure Stage | Code |")
            md.append("| --- | --- | --- | --- | --- |")
            for f in failures:
                md.append(
                    f"| `{f.get('taskId')}` | `{f.get('candidate')}` | "
                    f"{f.get('reward')} | `{f.get('failureStage')}` | `{f.get('failureCode')}` |"
                )
            md.append("")

    return "\n".join(md)


def render_html(report_data: dict[str, Any]) -> str:
    """Renders a minimal self-contained HTML report."""
    run_id = html.escape(str(report_data.get("runId", "")))
    status = html.escape(str(report_data.get("status", "")))
    pre = html.escape(json.dumps(report_data, indent=2, ensure_ascii=False))
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>Haifa Agent Ladder Report {run_id}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;}"
        "pre{background:#f6f8fa;padding:1rem;border-radius:6px;overflow:auto;}"
        "</style></head><body>"
        f"<h1>Haifa Agent Ladder Report: {run_id}</h1>"
        f"<p>Status: <strong>{status}</strong></p>"
        f"<pre>{pre}</pre>"
        "</body></html>\n"
    )
