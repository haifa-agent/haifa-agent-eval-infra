"""Deterministic projection of Harbor (haifa-agent-evals) CSV evidence."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


def summarize_harbor(
    evals_summary: dict[str, Any] | None,
    results_csv_path: Path | None,
) -> dict[str, Any]:
    """Builds a deterministic Harbor evals summary from results.csv artifacts."""
    summary = dict(evals_summary or {})
    rows: list[dict[str, str]] = []
    if results_csv_path is not None and results_csv_path.is_file():
        with results_csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    if rows:
        summary["attemptCount"] = len(rows)
        candidates = sorted({row.get("candidate", "") for row in rows if row.get("candidate")})
        if candidates:
            summary["candidates"] = candidates
        rewards: list[float] = []
        for row in rows:
            raw = row.get("reward", "")
            if raw == "":
                rewards.append(0.0)
                continue
            try:
                rewards.append(float(raw))
            except ValueError:
                rewards.append(0.0)
        summary.setdefault("rewardSum", sum(rewards))
        summary["rewardMean"] = sum(rewards) / len(rewards) if rewards else 0.0
        summary["passed"] = sum(1 for reward in rewards if reward >= 1.0)
    passes = int(summary.get("passed", 0) or 0)
    total = int(summary.get("attemptCount", 0) or 0)

    by_candidate: Counter[str] = Counter()
    passed_by_candidate: Counter[str] = Counter()
    failed_rows: list[dict[str, Any]] = []
    for row in rows:
        candidate = row.get("candidate", "") or "unknown"
        by_candidate[candidate] += 1
        raw = row.get("reward", "")
        try:
            reward = float(raw) if raw != "" else 0.0
        except ValueError:
            reward = 0.0
        if reward >= 1.0:
            passed_by_candidate[candidate] += 1
        else:
            failed_rows.append(
                {
                    "taskId": row.get("task_id", ""),
                    "candidate": candidate,
                    "reward": row.get("reward", ""),
                    "failureStage": row.get("failure_stage", ""),
                    "failureCode": row.get("failure_code", ""),
                    "errorType": row.get("error_type", ""),
                }
            )

    return {
        **summary,
        "totalAttempts": total,
        "passRate": round(passes / total, 4) if total else 0.0,
        "score": f"{passes}/{total}",
        "passed": total > 0 and passes == total,
        "perCandidate": {
            candidate: {
                "attempts": count,
                "passed": passed_by_candidate.get(candidate, 0),
            }
            for candidate, count in sorted(by_candidate.items())
        },
        "failures": failed_rows,
    }
