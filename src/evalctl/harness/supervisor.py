"""Autonomous-delivery ladder execution supervisor with safe progress extraction."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evalctl.config.schema import RunRequest
from evalctl.core.errors import ExecutionError
from evalctl.transport.ssh import SSHTransport

RUN_PATTERN = re.compile(r"^LADDER_RUN\s+cases=(\d+)\s+repeat=(\d+)\s+total=(\d+)$")
CASE_RESULT_PATTERN = re.compile(
    r"^\s*\[\s*(\d+)/(\d+)\]\s+(\S+?)(?:\.(\d+))?\s+"
    r"(PASSED|FAILED|INCOMPLETE_BUDGET)\b"
)
PROGRESS_PATTERN = re.compile(
    r"^\s*progress\s+(\d+)/(\d+)\s+PASSED\s+(\d+)\s+\((\d+)%\)\s+"
    r"FAILED\s+(\d+)\s+INCOMPLETE_BUDGET\s+(\d+)"
)
SUMMARY_PATTERN = re.compile(
    r"^runs=(\d+)\s+passed=(\d+)\s+failed=(\d+)\s+incompleteBudget=(\d+)"
)


class SafeProgressTracker:
    """Parses and sanitizes autonomous-delivery ladder progress lines.

    Only structured control markers are forwarded; free-form agent output
    (including the truncated heartbeat tail) is never surfaced.
    """

    def __init__(self, on_progress: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.on_progress = on_progress
        self.latest: dict[str, Any] | None = None

    def _emit(self, data: dict[str, Any]) -> None:
        self.latest = data
        if self.on_progress:
            self.on_progress(data)

    def handle_line(self, line: str) -> None:
        clean_line = line.strip()

        match = RUN_PATTERN.match(clean_line)
        if match:
            cases, repeat, total = match.groups()
            self._emit(
                {"kind": "run", "cases": int(cases), "repeat": int(repeat), "total": int(total)}
            )
            return

        match = PROGRESS_PATTERN.match(clean_line)
        if match:
            done, total, passed, percent, failed, incomplete = match.groups()
            self._emit(
                {
                    "kind": "progress",
                    "evaluated": int(done),
                    "total": int(total),
                    "passed": int(passed),
                    "percent": int(percent),
                    "failed": int(failed),
                    "incompleteBudget": int(incomplete),
                }
            )
            return

        match = SUMMARY_PATTERN.match(clean_line)
        if match:
            runs, passed, failed, incomplete = match.groups()
            self._emit(
                {
                    "kind": "summary",
                    "runs": int(runs),
                    "passed": int(passed),
                    "failed": int(failed),
                    "incompleteBudget": int(incomplete),
                }
            )
            return

        match = CASE_RESULT_PATTERN.match(clean_line)
        if match:
            done, total, case_id, attempt, status = match.groups()
            self._emit(
                {
                    "kind": "case",
                    "evaluated": int(done),
                    "total": int(total),
                    "caseId": case_id,
                    "attempt": int(attempt) if attempt else 1,
                    "status": status,
                }
            )


def build_ladder_spec(request: RunRequest, secrets_path: str, action: str = "run") -> dict[str, Any]:
    """Builds the JSON run spec consumed by remote/supervisor.sh."""
    worktree = f"/var/lib/haifa-eval/worktrees/{request.runId}/haifa-agent"
    evaluation = request.evaluation
    return {
        "runId": request.runId,
        "action": action,
        "runUser": "haifa-eval",
        "worktree": worktree,
        "agentDistDir": f"{evaluation.agentDistributionDir}/{request.runId}",
        "assetsCacheDir": evaluation.assetsCacheDir,
        "outputDir": f"{request.output.remoteEvidenceRoot}/{request.runId}",
        "runLadder": (
            f"{worktree}/haifa-agent-testing/haifa-agent-autonomous-delivery/tools/run-ladder.sh"
        ),
        "caseSet": evaluation.caseSet,
        "cases": evaluation.cases,
        "repeat": evaluation.repeat,
        "timeoutScale": evaluation.timeoutScale,
        "model": evaluation.modelId,
        "approval": evaluation.approval,
        "rehearse": evaluation.rehearse,
        "secretsPath": secrets_path,
    }


def execute_ladder_run(
    transport: SSHTransport,
    request: RunRequest,
    secrets_path: str,
    local_journal_file: Path,
    local_supervisor_script: Path,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    verbose: bool = False,
    action: str = "run",
) -> int:
    """Executes the ladder run via the remote supervisor and streams safe progress."""
    local_journal_file.parent.mkdir(parents=True, exist_ok=True)
    remote_control_dir = f"/var/lib/haifa-eval/runs/{request.runId}/control"
    remote_spec_path = f"{remote_control_dir}/ladder-spec.json"
    remote_script_path = f"{remote_control_dir}/supervisor.sh"

    transport.run_command(["mkdir", "-p", remote_control_dir])

    spec_content = json.dumps(build_ladder_spec(request, secrets_path, action), indent=2)
    res_spec = transport.run_command(
        ["bash", "-c", 'cat > "$1"', "_", remote_spec_path],
        stdin_data=spec_content,
        timeout=15,
    )
    if res_spec.returncode != 0:
        raise ExecutionError(f"Failed to upload ladder spec: {res_spec.stderr}")

    script_content = local_supervisor_script.read_text(encoding="utf-8")
    res_sup = transport.run_command(
        ["bash", "-c", 'cat > "$1" && chmod +x "$1"', "_", remote_script_path],
        stdin_data=script_content,
        timeout=15,
    )
    if res_sup.returncode != 0:
        raise ExecutionError(f"Failed to upload supervisor script: {res_sup.stderr}")

    tracker = SafeProgressTracker(on_progress=on_progress)

    with local_journal_file.open("a", encoding="utf-8") as journal:

        def stream_callback(line: str) -> None:
            journal.write(line)
            journal.flush()
            if verbose:
                print(line, end="", flush=True)
            tracker.handle_line(line)

        cmd = ["bash", remote_script_path, request.runId, remote_spec_path]
        exit_code = transport.stream_command(cmd, on_line=stream_callback)

    if exit_code != 0:
        raise ExecutionError(f"Ladder run failed with exit code {exit_code}")

    return exit_code
