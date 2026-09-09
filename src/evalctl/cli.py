"""evalctl CLI entry point and subcommands."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from evalctl.config.env import load_env_file
from evalctl.config.loader import load_run_request
from evalctl.core.cleanup import perform_run_cleanup
from evalctl.core.errors import EvalctlError
from evalctl.core.lifecycle import LifecycleManager, LifecycleStage
from evalctl.evidence.puller import pull_and_verify_evidence
from evalctl.harness.approval import verify_and_record_approval
from evalctl.harness.plan import generate_plan_set
from evalctl.harness.secret import EphemeralSecretManager
from evalctl.harness.supervisor import execute_suite_run
from evalctl.host.bootstrap import run_host_bootstrap
from evalctl.host.doctor import run_host_doctor
from evalctl.host.trust import verify_host_key
from evalctl.report.builder import build_evaluation_report
from evalctl.report.renderers import render_json, render_markdown, render_terminal
from evalctl.source.manager import prepare_sources
from evalctl.transport.ssh import SSHTransport

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def get_transport(request, local_run_dir: Path) -> SSHTransport:
    key_file_env = request.target.sshPrivateKeyFileEnv
    key_path_str = os.getenv(key_file_env)
    if not key_path_str:
        raise EvalctlError(f"Host SSH key environment variable '{key_file_env}' is not set")
    key_path = Path(key_path_str.strip().strip("\"'")).resolve()
    known_hosts = local_run_dir / "control" / "known_hosts"
    return SSHTransport(
        host=request.target.address,
        user=request.target.user,
        key_path=key_path,
        port=request.target.port,
        known_hosts_path=known_hosts if known_hosts.exists() else None,
    )


def build_parser() -> argparse.ArgumentParser:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--env-file",
        default=argparse.SUPPRESS,
        help="Path to .env credential file (defaults to ./.env in current directory if present)",
    )
    common_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable real-time verbose output of remote commands",
    )

    parser = argparse.ArgumentParser(
        prog="evalctl",
        description="Haifa Agent Fresh Machine Evaluation Control Plane",
        parents=[common_parser],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # request validate
    p_req = subparsers.add_parser("request", help="Run Request operations", parents=[common_parser])
    req_subs = p_req.add_subparsers(dest="subcommand", required=True)
    p_req_val = req_subs.add_parser(
        "validate", help="Validate a Run Request YAML file", parents=[common_parser]
    )
    p_req_val.add_argument("--file", required=True, help="Path to Run Request YAML")

    # host trust / doctor / bootstrap
    p_host = subparsers.add_parser("host", help="Host operations", parents=[common_parser])
    host_subs = p_host.add_subparsers(dest="subcommand", required=True)

    p_host_trust = host_subs.add_parser(
        "trust", help="Verify or discover remote host key", parents=[common_parser]
    )
    p_host_trust.add_argument("--file", required=True, help="Path to Run Request YAML")

    p_host_doc = host_subs.add_parser(
        "doctor", help="Run read-only preflight on remote host", parents=[common_parser]
    )
    p_host_doc.add_argument("--file", required=True, help="Path to Run Request YAML")

    p_host_boot = host_subs.add_parser(
        "bootstrap", help="Bootstrap packages and toolchain on remote host", parents=[common_parser]
    )
    p_host_boot.add_argument("--file", required=True, help="Path to Run Request YAML")

    # source prepare
    p_src = subparsers.add_parser("source", help="Source management", parents=[common_parser])
    src_subs = p_src.add_subparsers(dest="subcommand", required=True)
    p_src_prep = src_subs.add_parser(
        "prepare", help="Clone and pin exact commits on remote", parents=[common_parser]
    )
    p_src_prep.add_argument("--file", required=True, help="Path to Run Request YAML")

    # plan
    p_plan = subparsers.add_parser(
        "plan", help="Generate Harness execution plan and Plan Set", parents=[common_parser]
    )
    p_plan.add_argument("--file", required=True, help="Path to Run Request YAML")

    # run
    p_run = subparsers.add_parser(
        "run", help="Execute approved evaluation run", parents=[common_parser]
    )
    p_run.add_argument("--file", required=True, help="Path to Run Request YAML")
    p_run.add_argument(
        "--approved-plan-set", required=True, help="SHA-256 digest of approved plan-set.json"
    )

    # status
    p_stat = subparsers.add_parser("status", help="Check run status", parents=[common_parser])
    p_stat.add_argument("--file", required=True, help="Path to Run Request YAML")

    # logs
    p_logs = subparsers.add_parser("logs", help="View journal logs", parents=[common_parser])
    p_logs.add_argument("--file", required=True, help="Path to Run Request YAML")
    p_logs.add_argument("--follow", action="store_true", help="Follow live output")

    # collect
    p_col = subparsers.add_parser(
        "collect", help="Pull and verify evidence root", parents=[common_parser]
    )
    p_col.add_argument("--file", required=True, help="Path to Run Request YAML")

    # report
    p_rep = subparsers.add_parser(
        "report", help="Generate deterministic evaluation report", parents=[common_parser]
    )
    p_rep.add_argument("--file", required=True, help="Path to Run Request YAML")
    p_rep.add_argument("--format", choices=["terminal", "json", "markdown"], default="terminal")

    # cleanup
    p_cln = subparsers.add_parser(
        "cleanup", help="Safely clean up remote run worktree and units", parents=[common_parser]
    )
    p_cln.add_argument("--file", required=True, help="Path to Run Request YAML")
    p_cln.add_argument(
        "--include-evidence", action="store_true", help="Also remove remote evidence"
    )
    p_cln.add_argument("--force", action="store_true", help="Force cleanup without local receipt")

    return parser


def main(args: list[str] | None = None) -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(errors="replace")
        except Exception:
            pass

    parser = build_parser()
    parsed = parser.parse_args(args)

    try:
        # Automatically load .env (defaults to ./.env if present, or specified --env-file)
        loaded_env_path = load_env_file(getattr(parsed, "env_file", None))
        if loaded_env_path and getattr(parsed, "env_file", None):
            print(f"[evalctl] Loaded environment from: {loaded_env_path}")
        if parsed.command == "request" and parsed.subcommand == "validate":
            request, _, sha = load_run_request(parsed.file, validate_local_keys=False)
            print(f"[evalctl] Run Request valid: runId='{request.runId}', canonicalSha256='{sha}'")
            return 0

        # Commands that load full request
        request, _, request_sha = load_run_request(parsed.file, validate_local_keys=False)
        local_run_dir = Path(request.output.localResultRoot) / request.runId
        control_dir = local_run_dir / "control"
        lifecycle = LifecycleManager(request.runId, control_dir)

        if parsed.command == "host" and parsed.subcommand == "trust":
            known_hosts = control_dir / "known_hosts"
            fp = verify_host_key(request, known_hosts)
            lifecycle.record(LifecycleStage.HOST_TRUSTED, extra={"hostKeySha256": fp})
            print(f"[evalctl] Host key verified and trusted: {fp}")
            return 0

        transport = get_transport(request, local_run_dir)

        if parsed.command == "host" and parsed.subcommand == "doctor":
            doctor_script = REPO_ROOT / "remote" / "doctor.sh"
            report = run_host_doctor(transport, request, doctor_script)
            lifecycle.record(LifecycleStage.HOST_PREFLIGHTED, extra=report)
            print("[evalctl] Host preflight doctor checks PASSED.")
            return 0

        verbose = getattr(parsed, "verbose", False)

        if parsed.command == "host" and parsed.subcommand == "bootstrap":
            boot_script = REPO_ROOT / "remote" / "bootstrap.sh"
            lockfile = REPO_ROOT / "lockfiles" / "bootstrap-ubuntu-26.04.json"
            facts_dir = control_dir / "host_facts"
            facts = run_host_bootstrap(
                transport, request, boot_script, lockfile, facts_dir, verbose=verbose
            )
            lifecycle.record(LifecycleStage.BOOTSTRAPPED, extra=facts)
            print(f"[evalctl] Host bootstrap completed. Toolchain facts saved to {facts_dir}")
            return 0

        if parsed.command == "source" and parsed.subcommand == "prepare":
            src_script = REPO_ROOT / "remote" / "source-prepare.sh"
            manifest = prepare_sources(transport, request, src_script, control_dir, verbose=verbose)
            lifecycle.record(LifecycleStage.SOURCE_PINNED, artifacts=manifest)
            print(f"[evalctl] Sources prepared and pinned for run {request.runId}")
            return 0

        if parsed.command == "plan":
            plans_dir = local_run_dir / "plans"
            plan_set = generate_plan_set(transport, request, request_sha, plans_dir, verbose=verbose)
            lifecycle.record(
                LifecycleStage.PLAN_CREATED,
                artifacts={"planSetSha256": plan_set["planSetSha256"]},
            )
            lifecycle.record(LifecycleStage.WAITING_APPROVAL)
            print("[evalctl] Plan Set generated successfully.")
            print(f"  Plan Set Digest: {plan_set['planSetSha256']}")
            print("  Status: WAITING_APPROVAL. To execute, run:")
            print(
                f"    evalctl run --file {parsed.file} --approved-plan-set {plan_set['planSetSha256']}"
            )
            return 0

        if parsed.command == "run":
            plans_dir = local_run_dir / "plans"
            verify_and_record_approval(
                parsed.approved_plan_set, plans_dir, operator_id=os.getlogin()
            )
            lifecycle.record(
                LifecycleStage.RUNNING,
                extra={"approvedPlanSet": parsed.approved_plan_set},
            )

            secret_mgr = EphemeralSecretManager(transport, request)
            secrets_path = secret_mgr.inject_secrets()
            try:
                sup_script = REPO_ROOT / "remote" / "supervisor.sh"
                for s_spec in request.evaluation.runs:
                    print(f"[evalctl] Starting suite: {s_spec.id} ({s_spec.suite})...")
                    jfile = control_dir / f"{s_spec.id}.journal"
                    execute_suite_run(
                        transport,
                        request,
                        s_spec,
                        secrets_path,
                        jfile,
                        sup_script,
                        on_progress=lambda p: print(
                            f"  [progress] phase={p['phase']} evaluated={p['evaluated']} passed={p['passed']} current={p['currentCase']}"
                        ),
                        verbose=verbose,
                    )
                lifecycle.record(LifecycleStage.EVIDENCE_READY)
                print(
                    "[evalctl] Evaluation run completed successfully. Evidence is ready for collection."
                )
            finally:
                secret_mgr.destroy_secrets()
            return 0

        if parsed.command == "status":
            latest = lifecycle.latest_stage()
            print(f"[evalctl] Run {request.runId} latest stage: {latest}")
            return 0

        if parsed.command == "logs":
            if getattr(parsed, "follow", False):
                remote_journals = f"/var/lib/haifa-eval/runs/{request.runId}/journals"
                cmd = [
                    "bash",
                    "-c",
                    f"mkdir -p '{remote_journals}' && tail -n 50 -F '{remote_journals}'/*.journal 2>/dev/null",
                ]
                print(f"[evalctl] Streaming remote logs for run {request.runId} (Ctrl+C to stop)...")
                try:
                    transport.stream_command(cmd, on_line=lambda l: print(l, end="", flush=True))
                except KeyboardInterrupt:
                    print("\n[evalctl] Stopped log following.")
                return 0

            journal_files = list(control_dir.glob("*.journal"))
            if not journal_files:
                res = transport.run_command(
                    [
                        "bash",
                        "-c",
                        f"cat /var/lib/haifa-eval/runs/{request.runId}/journals/*.journal 2>/dev/null || true",
                    ]
                )
                if res.stdout.strip():
                    print(res.stdout)
                    return 0
                print(f"[evalctl] No journal logs found for run {request.runId}")
                return 0
            for jf in journal_files:
                print(f"--- Log: {jf.name} ---")
                print(jf.read_text(encoding="utf-8"))
            return 0

        if parsed.command == "collect":
            evidence_dir = local_run_dir / "evidence"
            receipt = pull_and_verify_evidence(transport, request, evidence_dir)
            lifecycle.record(LifecycleStage.EVIDENCE_PULLED, artifacts=receipt)
            print(
                f"[evalctl] Evidence collected and verified: {receipt['verifiedFileCount']} files."
            )
            return 0

        if parsed.command == "report":
            report_data = build_evaluation_report(request, local_run_dir)
            lifecycle.record(LifecycleStage.REPORT_READY, extra={"status": report_data["status"]})
            lifecycle.record(LifecycleStage.COMPLETE)
            if parsed.format == "json":
                print(render_json(report_data))
            elif parsed.format == "markdown":
                print(render_markdown(report_data))
            else:
                print(render_terminal(report_data))
            return 0

        if parsed.command == "cleanup":
            cleanup_script = REPO_ROOT / "remote" / "cleanup.sh"
            perform_run_cleanup(
                transport,
                request,
                local_run_dir,
                cleanup_script,
                include_evidence=parsed.include_evidence,
                force=parsed.force,
            )
            print(f"[evalctl] Cleaned up remote run {request.runId}")
            return 0

    except EvalctlError as exc:
        print(f"[evalctl] ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[evalctl] UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
