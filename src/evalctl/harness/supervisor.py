"""Harness execution supervisor with safe progress extraction."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from evalctl.config.schema import RunRequest, SuiteRunSpec
from evalctl.core.errors import ExecutionError
from evalctl.transport.ssh import SSHTransport

PROGRESS_PATTERN = re.compile(
    r"^\[delivery-progress\] phase=(\S+) evaluated=(\d+)/(\d+) "
    r"passed=(\d+)/(\d+) currentCase=(\S+) currentRepetition=(\S+)$"
)


class SafeProgressTracker:
    """Parses and sanitizes harness progress lines."""

    def __init__(self, on_progress: Callable[[dict[str, str]], None] | None = None) -> None:
        self.on_progress = on_progress
        self.latest: dict[str, str] | None = None

    def handle_line(self, line: str) -> None:
        clean_line = line.strip()
        match = PROGRESS_PATTERN.match(clean_line)
        if match:
            phase, evaluated, total, passed, passed_total, case_id, rep = match.groups()
            data = {
                "phase": phase,
                "evaluated": f"{evaluated}/{total}",
                "passed": f"{passed}/{passed_total}",
                "currentCase": case_id,
                "currentRepetition": rep,
            }
            self.latest = data
            if self.on_progress:
                self.on_progress(data)


def execute_suite_run(
    transport: SSHTransport,
    request: RunRequest,
    suite_spec: SuiteRunSpec,
    secrets_path: str,
    local_journal_file: Path,
    local_supervisor_script: Path,
    on_progress: Callable[[dict[str, str]], None] | None = None,
) -> int:
    """Executes a single suite via supervisor and streams safe progress to local journal."""
    local_journal_file.parent.mkdir(parents=True, exist_ok=True)
    worktree = f"/var/lib/haifa-eval/worktrees/{request.runId}"
    plan_path = f"/var/lib/haifa-eval/plans/{request.runId}/{suite_spec.id}.json"

    script_content = local_supervisor_script.read_text(encoding="utf-8")
    remote_script_path = (
        f"/var/lib/haifa-eval/runs/{request.runId}/control/supervisor-{suite_spec.id}.sh"
    )

    # Upload supervisor script
    transport.run_command(["mkdir", "-p", f"/var/lib/haifa-eval/runs/{request.runId}/control"])
    transport.run_command(
        ["bash", "-c", f"cat > {remote_script_path} && chmod +x {remote_script_path}"],
        stdin_data=script_content,
        timeout=15,
    )

    tracker = SafeProgressTracker(on_progress=on_progress)

    # Stream execution
    with local_journal_file.open("a", encoding="utf-8") as journal:

        def stream_callback(line: str) -> None:
            journal.write(line)
            journal.flush()
            tracker.handle_line(line)

        cmd = [
            "bash",
            remote_script_path,
            request.runId,
            suite_spec.id,
            plan_path,
            suite_spec.approveBudget,
            worktree,
            secrets_path,
        ]
        exit_code = transport.stream_command(cmd, on_line=stream_callback)

    if exit_code != 0:
        raise ExecutionError(f"Suite execution '{suite_spec.id}' failed with exit code {exit_code}")

    return exit_code
