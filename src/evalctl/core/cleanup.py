"""Safe, bounded run cleanup coordinator."""

from __future__ import annotations

from pathlib import Path

from evalctl.config.schema import RunRequest
from evalctl.core.errors import CleanupError
from evalctl.transport.ssh import SSHTransport


def perform_run_cleanup(
    transport: SSHTransport,
    request: RunRequest,
    local_run_dir: Path,
    local_cleanup_script: Path,
    include_evidence: bool = False,
    force: bool = False,
) -> None:
    """Executes remote cleanup for a single validated runId with safety checks."""
    run_id = request.runId
    if not run_id or "/" in run_id or "*" in run_id or run_id in (".", ".."):
        raise CleanupError(f"Refusing to cleanup invalid/dangerous runId: '{run_id}'")

    # Safety check: confirm local evidence exists if remote evidence is to be deleted
    receipt_file = local_run_dir / "evidence" / "transfer-receipt.json"
    if include_evidence and not receipt_file.is_file() and not force:
        raise CleanupError(
            f"Cannot cleanup remote evidence for '{run_id}' because local evidence "
            f"transfer-receipt.json is missing! Pass force=True if intentional."
        )

    script_content = local_cleanup_script.read_text(encoding="utf-8")
    args = ["sudo", "bash", "-s", "--", run_id]
    if include_evidence:
        args.append("--include-evidence")

    res = transport.run_command(args, stdin_data=script_content, timeout=60)
    if res.returncode != 0:
        raise CleanupError(f"Remote cleanup failed ({res.returncode}):\n{res.stderr}")
