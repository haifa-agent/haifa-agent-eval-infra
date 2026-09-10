"""Interactive self-contained HTML report generator with drill-down case details."""

from __future__ import annotations

import contextlib
import html
import json
from pathlib import Path
from typing import Any


def _escape(val: Any) -> str:
    return html.escape(str(val) if val is not None else "")


def _format_tokens(num: int | float | None) -> str:
    if num is None:
        return "0"
    return f"{int(num):,}"


def _format_diff_html(diff_text: str) -> str:
    if not diff_text or not diff_text.strip():
        return '<div class="empty-diff">无工作区代码修改 (workspaceChanged: false)</div>'

    lines = []
    for line in diff_text.splitlines():
        esc = html.escape(line)
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f'<div class="diff-line diff-header">{esc}</div>')
        elif line.startswith("@@"):
            lines.append(f'<div class="diff-line diff-hunk">{esc}</div>')
        elif line.startswith("+"):
            lines.append(f'<div class="diff-line diff-add">{esc}</div>')
        elif line.startswith("-"):
            lines.append(f'<div class="diff-line diff-del">{esc}</div>')
        else:
            lines.append(f'<div class="diff-line">{esc}</div>')
    return '<div class="diff-container">' + "".join(lines) + "</div>"


def enrich_autonomous_delivery_cases(
    cases: list[dict[str, Any]],
    evidence_dir: Path | None,
) -> list[dict[str, Any]]:
    """Enriches case list with deep diagnostic data (prompt, acceptance checks, git diff, usage)."""
    enriched: list[dict[str, Any]] = []

    # Try to load native results maps from ad-phase-*.json
    phase_native_map: dict[str, dict[str, Any]] = {}
    if evidence_dir and evidence_dir.is_dir():
        for pf in sorted(evidence_dir.glob("ad-phase-*.json")):
            with contextlib.suppress(Exception):
                data = json.loads(pf.read_text(encoding="utf-8"))
                for item in data.get("nativeResult", {}).get("results", []):
                    key = f"{item.get('caseId')}_{item.get('repetition', 1)}"
                    phase_native_map[key] = item

    for c in cases:
        c_copy = dict(c)
        case_id = str(c.get("caseId", ""))
        rep = c.get("repetition", 1)
        phase_name = c.get("phase", "")
        native_key = f"{case_id}_{rep}"
        native_item = phase_native_map.get(native_key, {})

        c_copy["language"] = native_item.get("language", c.get("language", "-"))
        c_copy["taskType"] = native_item.get("taskType", c.get("taskType", "-"))
        c_copy["capabilities"] = native_item.get("capabilities", [])
        c_copy["riskDimensions"] = native_item.get("riskDimensions", [])
        c_copy["modelCalls"] = native_item.get("modelCalls", c.get("modelCalls", 0))
        c_copy["toolCalls"] = native_item.get("toolCalls", c.get("toolCalls", 0))
        c_copy["inputTokens"] = native_item.get("inputTokens", c.get("inputTokens", 0))
        c_copy["outputTokens"] = native_item.get("outputTokens", c.get("outputTokens", 0))
        c_copy["wallTimeSeconds"] = native_item.get(
            "wallTimeSeconds", c.get("wallTimeSeconds", 0)
        )

        c_copy["prompt"] = ""
        c_copy["diff"] = ""
        c_copy["acceptanceChecks"] = {}
        c_copy["acceptanceFailures"] = []
        c_copy["repeatUsage"] = {}

        if evidence_dir and evidence_dir.is_dir():
            phase_suffix = phase_name.split("_")[-1].lower() if "_" in phase_name else "1"
            cand_dirs = [
                evidence_dir / f"ad-phase-{phase_suffix}" / f"case-{case_id}" / f"repeat-{int(rep):02d}",
                evidence_dir / f"ad-phase-{phase_suffix}" / f"case-{case_id}" / f"repeat-{rep}",
                evidence_dir / f"case-{case_id}" / f"repeat-{int(rep):02d}",
            ]
            target_dir = next((d for d in cand_dirs if d.is_dir()), None)

            if target_dir:
                prompt_file = target_dir / "attachments" / "immutable-case" / "prompt.txt"
                if prompt_file.is_file():
                    with contextlib.suppress(Exception):
                        c_copy["prompt"] = prompt_file.read_text(
                            encoding="utf-8", errors="replace"
                        ).strip()

                diff_file = target_dir / "attachments" / "workspace.diff"
                if diff_file.is_file():
                    with contextlib.suppress(Exception):
                        c_copy["diff"] = diff_file.read_text(
                            encoding="utf-8", errors="replace"
                        )

                acc_file = target_dir / "attachments" / "acceptance-result.json"
                if acc_file.is_file():
                    with contextlib.suppress(Exception):
                        acc_data = json.loads(acc_file.read_text(encoding="utf-8"))
                        c_copy["acceptanceChecks"] = acc_data.get("checks", {})
                        c_copy["acceptanceFailures"] = acc_data.get("failures", [])

                rep_file = target_dir / "repeat-result.json"
                if rep_file.is_file():
                    with contextlib.suppress(Exception):
                        rep_data = json.loads(rep_file.read_text(encoding="utf-8"))
                        c_copy["repeatUsage"] = rep_data.get("usage", {})

        enriched.append(c_copy)
    return enriched


def generate_html_report(report_data: dict[str, Any], local_run_dir: Path) -> str:
    """Renders a comprehensive, modern interactive single-file HTML report with drill-downs."""
    run_id = report_data.get("runId", "")
    status = report_data.get("status", "UNKNOWN")
    provider_id = report_data.get("providerId", "")
    model_id = report_data.get("modelId", "")
    profile = report_data.get("agentProfileRef", "")
    evaluated_at = report_data.get("evaluatedAt", "")

    evidence_dir = local_run_dir / "evidence"

    is_passed = "PASS" in status.upper() and "FAIL" not in status.upper()
    status_class = "status-pass" if is_passed else "status-fail"

    ad = report_data.get("autonomousDelivery")
    cp = report_data.get("criticalPath")

    currency_symbol = "¥"
    currency_code = "CNY"
    cost_val = 0.0
    if ad:
        cost_val = ad.get("aggregates", {}).get("estimatedCostUsd", 0.0)

    enriched_ad_cases = []
    if ad and ad.get("cases"):
        enriched_ad_cases = enrich_autonomous_delivery_cases(ad.get("cases", []), evidence_dir)

    if ad:
        score_text = ad.get("combinedScore", "0/0")
        total_eval = len(enriched_ad_cases)
        total_pass = sum(1 for c in enriched_ad_cases if c.get("gatePassed"))
        pass_pct = f"{(total_pass / total_eval * 100):.1f}%" if total_eval > 0 else "0%"
        agg = ad.get("aggregates", {})
        total_in_tok = _format_tokens(agg.get("inputTokens"))
        total_out_tok = _format_tokens(agg.get("outputTokens"))
        model_calls = agg.get("modelCalls", 0)
        tool_calls = agg.get("toolCalls", 0)
        dur_secs = agg.get("totalDurationSeconds", 0.0)
        dur_hrs = f"{dur_secs / 3600.0:.2f}h"
    elif cp:
        score_text = cp.get("coverage", "0/0")
        total_pass = cp.get("passedCases", 0)
        total_eval = cp.get("totalCases", 0)
        pass_pct = f"{(total_pass / total_eval * 100):.1f}%" if total_eval > 0 else "0%"
        total_in_tok = "-"
        total_out_tok = "-"
        model_calls = "-"
        tool_calls = "-"
        dur_secs = 0.0
        dur_hrs = "-"
        agg = {}
    else:
        score_text = "0/0"
        pass_pct = "0%"
        total_in_tok = "0"
        total_out_tok = "0"
        model_calls = 0
        tool_calls = 0
        dur_secs = 0.0
        dur_hrs = "0h"
        agg = {}

    html_parts = []
    html_parts.append(
        f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Haifa Agent 评测报告: {_escape(run_id)}</title>
<style>
:root {{
  --bg: #f8fafc;
  --surface: #ffffff;
  --text: #0f172a;
  --text-muted: #64748b;
  --border: #e2e8f0;
  --primary: #4f46e5;
  --primary-light: #eef2ff;
  --success: #10b981;
  --success-bg: #ecfdf5;
  --success-border: #a7f3d0;
  --danger: #ef4444;
  --danger-bg: #fef2f2;
  --danger-border: #fecaca;
  --warning: #f59e0b;
  --warning-bg: #fffbeb;
  --badge-bg: #f1f5f9;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: var(--font);
  background-color: var(--bg);
  color: var(--text);
  line-height: 1.5;
  padding: 32px 24px;
}}
.container {{
  max-width: 1280px;
  margin: 0 auto;
}}

/* Header */
.header {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
}}
.header-top {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 20px;
}}
.header-title h1 {{
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text);
}}
.header-title .subtitle {{
  color: var(--text-muted);
  font-size: 14px;
  margin-top: 4px;
}}
.status-pill {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 18px;
  border-radius: 9999px;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.02em;
}}
.status-pass {{
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid var(--success-border);
}}
.status-fail {{
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}}

/* Meta Grid */
.meta-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
}}
.meta-item .meta-label {{
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
}}
.meta-item .meta-value {{
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-top: 4px;
  font-family: var(--mono);
}}

/* KPI Dashboard Cards */
.kpi-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.kpi-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.02);
}}
.kpi-card .kpi-label {{
  font-size: 13px;
  font-weight: 500;
  color: var(--text-muted);
}}
.kpi-card .kpi-value {{
  font-size: 28px;
  font-weight: 700;
  margin-top: 6px;
  letter-spacing: -0.02em;
}}
.kpi-card .kpi-sub {{
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}}

/* Phases Breakdown Cards */
.phase-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}}
.phase-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px;
}}
.phase-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}}
.phase-title {{
  font-size: 16px;
  font-weight: 600;
}}
.phase-badge {{
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}}
.progress-track {{
  background: var(--badge-bg);
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  margin: 12px 0 8px 0;
}}
.progress-fill {{
  height: 100%;
  border-radius: 4px;
}}
.progress-fill.pass {{ background: var(--success); }}
.progress-fill.fail {{ background: var(--danger); }}

/* Control Panel / Filters */
.controls-bar {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}}
.filters {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}}
.filter-btn {{
  background: var(--badge-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  color: var(--text);
}}
.filter-btn:hover {{
  background: #e2e8f0;
}}
.filter-btn.active {{
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}}
.search-input {{
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 13px;
  width: 240px;
  outline: none;
}}
.search-input:focus {{
  border-color: var(--primary);
}}

/* Case Table & Accordions */
.case-item {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  margin-bottom: 12px;
  overflow: hidden;
  transition: box-shadow 0.15s ease;
}}
.case-item:hover {{
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}}
.case-summary {{
  display: grid;
  grid-template-columns: 120px 100px 90px 140px 100px 90px 120px 1fr 40px;
  padding: 14px 20px;
  align-items: center;
  cursor: pointer;
  user-select: none;
  font-size: 14px;
  gap: 12px;
}}
.case-summary:hover {{
  background: #fbfcfe;
}}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  text-align: center;
}}
.badge-pass {{ background: var(--success-bg); color: var(--success); border: 1px solid var(--success-border); }}
.badge-fail {{ background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger-border); }}
.badge-neutral {{ background: var(--badge-bg); color: var(--text-muted); }}
.chevron {{
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  transition: transform 0.2s ease;
}}
.case-item.expanded .chevron {{
  transform: rotate(180deg);
}}

/* Drill-Down Details */
.case-details {{
  display: none;
  padding: 24px;
  border-top: 1px solid var(--border);
  background: #fafbfc;
}}
.case-item.expanded .case-details {{
  display: block;
}}
.detail-section {{
  margin-bottom: 20px;
}}
.detail-section:last-child {{
  margin-bottom: 0;
}}
.detail-title {{
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 8px;
}}
.prompt-box {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 18px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  color: #334155;
}}
.checks-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}}
.check-item {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}}
.check-ok {{ color: var(--success); font-weight: 600; }}
.check-ng {{ color: var(--danger); font-weight: 600; }}

/* Git Diff Viewer */
.diff-container {{
  background: #1e1e2e;
  color: #cdd6f4;
  border-radius: 8px;
  padding: 12px 16px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 380px;
}}
.diff-line {{ white-space: pre; }}
.diff-header {{ color: #89b4fa; font-weight: 600; }}
.diff-hunk {{ color: #cba6f7; }}
.diff-add {{ background: rgba(166, 227, 161, 0.15); color: #a6e3a1; }}
.diff-del {{ background: rgba(243, 139, 168, 0.15); color: #f38ba8; }}
.empty-diff {{
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 14px;
  font-size: 13px;
  color: var(--text-muted);
  font-style: italic;
}}

/* Tag pills */
.tag-pill {{
  display: inline-block;
  background: #f1f5f9;
  color: #475569;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  margin-right: 4px;
}}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="header-top">
      <div class="header-title">
        <h1>Haifa Agent 评测报告: <code>{_escape(run_id)}</code></h1>
        <div class="subtitle">端到端全自主交付与关键路径评测收敛报告</div>
      </div>
      <div>
        <span class="status-pill {status_class}">● {_escape(status)}</span>
      </div>
    </div>

    <div class="meta-grid">
      <div class="meta-item">
        <div class="meta-label">评测模型 (Model)</div>
        <div class="meta-value">{_escape(model_id)}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">模型供应商 (Provider)</div>
        <div class="meta-value">{_escape(provider_id)}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">Agent 档案 (Profile)</div>
        <div class="meta-value">{_escape(profile)}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">评测时间 (Evaluated At)</div>
        <div class="meta-value" style="font-size: 13px;">{_escape(evaluated_at[:19]).replace('T', ' ')} UTC</div>
      </div>
    </div>
  </div>

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">综合得分 / 用例通过率</div>
      <div class="kpi-value" style="color: {'var(--success)' if is_passed else 'var(--primary)'};">{score_text}</div>
      <div class="kpi-sub">通过率: {pass_pct} (26项全量覆盖)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">总执行耗时</div>
      <div class="kpi-value">{dur_hrs}</div>
      <div class="kpi-sub">{dur_secs:.1f} 秒</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Token 消耗 (输入 / 输出)</div>
      <div class="kpi-value" style="font-size: 22px;">{total_in_tok} <span style="font-size: 14px; font-weight: 400; color: var(--text-muted);">/ {total_out_tok}</span></div>
      <div class="kpi-sub">总计: {_format_tokens(agg.get('inputTokens', 0) + agg.get('outputTokens', 0)) if ad else '-'} Tokens</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">交互调用 (Model / Tool)</div>
      <div class="kpi-value">{model_calls} <span style="font-size: 14px; font-weight: 400; color: var(--text-muted);">/ {tool_calls}</span></div>
      <div class="kpi-sub">模型轮次与 MCP 工具调用</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">估算开销 (Estimated Cost)</div>
      <div class="kpi-value">{currency_symbol}{cost_val:.2f} <span style="font-size: 14px; font-weight: 400; color: var(--text-muted);">{currency_code}</span></div>
      <div class="kpi-sub">核准上限: ¥39.00 CNY</div>
    </div>
  </div>
"""
    )

    if ad and ad.get("phases"):
        html_parts.append('  <div class="phase-grid">')
        for pname, pinfo in ad.get("phases", {}).items():
            ev = pinfo.get("evaluated", 0)
            ps = pinfo.get("passed", 0)
            pct = (ps / ev * 100) if ev > 0 else 0
            pstatus = pinfo.get("status", "FAIL")
            pbadge = "badge-pass" if pstatus == "PASS" else "badge-fail"
            fill_class = "pass" if pstatus == "PASS" else "fail"
            html_parts.append(
                f"""    <div class="phase-card">
      <div class="phase-header">
        <div class="phase-title">阶段: {_escape(pname)}</div>
        <span class="badge {pbadge}">{_escape(pstatus)}</span>
      </div>
      <div style="font-size: 22px; font-weight: 700;">{ps} / {ev} <span style="font-size: 13px; font-weight: 500; color: var(--text-muted);">({pct:.1f}%)</span></div>
      <div class="progress-track">
        <div class="progress-fill {fill_class}" style="width: {pct:.1f}%;"></div>
      </div>
    </div>"""
            )
        html_parts.append("  </div>")

    # Controls Bar
    html_parts.append(
        """  <!-- Controls Bar -->
  <div class="controls-bar">
    <div class="filters">
      <button class="filter-btn active" onclick="filterCases('all', this)">全部用例</button>
      <button class="filter-btn" onclick="filterCases('pass', this)">通过 (PASS)</button>
      <button class="filter-btn" onclick="filterCases('fail', this)">未通过 (FAIL)</button>
      <button class="filter-btn" onclick="filterCases('PHASE_1', this)">Phase 1</button>
      <button class="filter-btn" onclick="filterCases('PHASE_2', this)">Phase 2</button>
      <button class="filter-btn" onclick="filterCases('PHASE_3', this)">Phase 3</button>
    </div>
    <div>
      <input type="text" id="caseSearch" class="search-input" placeholder="搜索用例 ID / 语言 / 任务类型..." onkeyup="searchCases()">
    </div>
  </div>
"""
    )

    # Cases list
    html_parts.append('  <div class="cases-list" id="casesList">')

    for c in enriched_ad_cases:
        cid = str(c.get("caseId", ""))
        rep = c.get("repetition", 1)
        pname = c.get("phase", "")
        lang = c.get("language", "-")
        ttype = c.get("taskType", "-")
        gate_ok = c.get("gatePassed", False)
        acc_ok = c.get("hiddenAcceptance", False)
        dur_sec = c.get("wallTimeSeconds", 0.0)

        item_status_class = "case-pass" if gate_ok else "case-fail"
        gate_badge = (
            '<span class="badge badge-pass">GATE PASS</span>'
            if gate_ok
            else '<span class="badge badge-fail">GATE FAIL</span>'
        )
        acc_badge = (
            '<span class="badge badge-pass">ACC PASS</span>'
            if acc_ok
            else '<span class="badge badge-fail">ACC FAIL</span>'
        )

        failures = c.get("acceptanceFailures", [])
        failures_html = (
            " ".join(
                f'<span class="tag-pill" style="color: var(--danger); background: var(--danger-bg);">{_escape(f)}</span>'
                for f in failures
            )
            if failures
            else '<span style="color: var(--success); font-size: 12px;">全部验收项通过</span>'
        )

        checks = c.get("acceptanceChecks", {})
        checks_html_list = []
        for chk_name, chk_res in checks.items():
            res_str = (
                '<span class="check-ok">✓ 通过</span>'
                if chk_res
                else '<span class="check-ng">✗ 失败</span>'
            )
            checks_html_list.append(
                f'<div class="check-item"><span>{_escape(chk_name)}</span>{res_str}</div>'
            )
        checks_html = (
            "".join(checks_html_list)
            if checks_html_list
            else '<div style="color: var(--text-muted); font-size: 13px;">无独立检查项数据</div>'
        )

        diff_html = _format_diff_html(c.get("diff", ""))
        prompt_text = c.get("prompt") or "(无任务提示词或内置套件用例)"

        html_parts.append(
            f"""    <div class="case-item {item_status_class}" data-phase="{_escape(pname)}" data-status="{'pass' if gate_ok else 'fail'}" data-keywords="{_escape(cid)} {_escape(lang)} {_escape(ttype)} {_escape(pname)}">
      <div class="case-summary" onclick="toggleCase(this.parentElement)">
        <div style="font-weight: 700; font-family: var(--mono); color: var(--primary);">Case {_escape(cid)} <span style="font-size: 11px; color: var(--text-muted); font-weight: 400;">(r{rep})</span></div>
        <div><span class="tag-pill">{_escape(pname)}</span></div>
        <div style="font-family: var(--mono); font-size: 12px;">{_escape(lang)}</div>
        <div style="font-size: 12px; color: var(--text-muted);">{_escape(ttype)}</div>
        <div style="font-family: var(--mono); font-size: 12px;">{dur_sec:.1f}s</div>
        <div>{gate_badge}</div>
        <div>{acc_badge}</div>
        <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{failures_html}</div>
        <div class="chevron">▼</div>
      </div>

      <div class="case-details">
        <div class="detail-section">
          <div class="detail-title">任务原始指令 (Task Prompt)</div>
          <div class="prompt-box">{_escape(prompt_text)}</div>
        </div>

        <div class="detail-section">
          <div class="detail-title">自动化验收检查项矩阵 (Acceptance Check Matrix)</div>
          <div class="checks-grid">
            {checks_html}
          </div>
        </div>

        <div class="detail-section">
          <div class="detail-title">工作区代码变更差异 (Git Workspace Diff)</div>
          {diff_html}
        </div>

        <div class="detail-section">
          <div class="detail-title">资源与交互指标 (Execution Metrics)</div>
          <div style="display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; font-family: var(--mono);">
            <div class="check-item" style="flex: 1;"><span>输入 Token:</span> <b>{_format_tokens(c.get('inputTokens'))}</b></div>
            <div class="check-item" style="flex: 1;"><span>输出 Token:</span> <b>{_format_tokens(c.get('outputTokens'))}</b></div>
            <div class="check-item" style="flex: 1;"><span>模型调用:</span> <b>{c.get('modelCalls', 0)} 次</b></div>
            <div class="check-item" style="flex: 1;"><span>工具调用:</span> <b>{c.get('toolCalls', 0)} 次</b></div>
            <div class="check-item" style="flex: 1;"><span>执行时长:</span> <b>{dur_sec:.2f}s</b></div>
          </div>
        </div>
      </div>
    </div>"""
        )

    html_parts.append("  </div>")

    if cp:
        html_parts.append(
            f"""  <div class="header" style="margin-top: 24px;">
    <h2 style="font-size: 18px; margin-bottom: 12px;">关键路径评测 (Critical Path)</h2>
    <div style="font-size: 14px; margin-bottom: 8px;">套件: <code>{_escape(cp.get('suiteId'))}</code> | 覆盖率: <b>{_escape(cp.get('coverage'))}</b></div>
  </div>"""
        )

    html_parts.append(
        """</div> <!-- container -->

<script>
function toggleCase(el) {
  el.classList.toggle('expanded');
}

let currentFilter = 'all';

function filterCases(filterType, btnEl) {
  currentFilter = filterType;
  if (btnEl) {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btnEl.classList.add('active');
  }
  applyFilters();
}

function searchCases() {
  applyFilters();
}

function applyFilters() {
  const query = (document.getElementById('caseSearch').value || '').toLowerCase().trim();
  const items = document.querySelectorAll('.case-item');

  items.forEach(item => {
    const phase = item.getAttribute('data-phase');
    const status = item.getAttribute('data-status');
    const keywords = (item.getAttribute('data-keywords') || '').toLowerCase();

    let matchesFilter = true;
    if (currentFilter === 'pass' && status !== 'pass') matchesFilter = false;
    else if (currentFilter === 'fail' && status !== 'fail') matchesFilter = false;
    else if (currentFilter.startsWith('PHASE_') && phase !== currentFilter) matchesFilter = false;

    let matchesQuery = true;
    if (query && !keywords.includes(query)) {
      matchesQuery = false;
    }

    if (matchesFilter && matchesQuery) {
      item.style.display = '';
    } else {
      item.style.display = 'none';
    }
  });
}
</script>
</body>
</html>
"""
    )

    return "\n".join(html_parts)
