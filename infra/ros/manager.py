#!/usr/bin/env python3
"""ROS Stack Manager for Haifa Agent Evaluation Spot Instances."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

DEFAULT_INFRA_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEFAULT_INFRA_DIR.parent.parent


def find_aliyun_executable() -> str:
    """Locate the aliyun CLI executable."""
    env_override = os.getenv("ALIYUN_CLI_PATH")
    if env_override and Path(env_override).is_file():
        return env_override

    found = shutil.which("aliyun")
    if found:
        return found

    # Fallback to common/known installation directories on Windows
    candidate_paths = [
        r"D:\dev\software\aliyuncli\aliyun.exe",
        r"C:\dev\software\aliyuncli\aliyun.exe",
        r"C:\Program Files\aliyuncli\aliyun.exe",
        Path.home() / "aliyuncli" / "aliyun.exe",
        Path.home() / ".aliyun" / "bin" / "aliyun.exe",
    ]
    for p in candidate_paths:
        p_path = Path(p)
        if p_path.is_file():
            return str(p_path)

    raise RuntimeError(
        "Could not find 'aliyun' CLI executable. Please ensure aliyun CLI is in PATH "
        "or set ALIYUN_CLI_PATH environment variable."
    )


class ROSManager:
    """Manages ROS stacks for spot instance lifecycle."""

    def __init__(
        self,
        template_file: Path | None = None,
        parameters_file: Path | None = None,
        state_file: Path | None = None,
    ):
        self.infra_dir = DEFAULT_INFRA_DIR
        self.template_file = (
            template_file or self.infra_dir / "spot-instance-template.yaml"
        ).resolve()
        self.parameters_file = (
            parameters_file or self.infra_dir / "parameters.yaml"
        ).resolve()
        self.state_file = (
            state_file or self.infra_dir / ".active_stack.json"
        ).resolve()
        self.aliyun_bin = find_aliyun_executable()

    def load_config(self) -> tuple[str, str, dict[str, Any]]:
        """Load region, prefix, and parameters from parameters.yaml."""
        if not self.parameters_file.exists():
            raise FileNotFoundError(
                f"Parameters file not found at: {self.parameters_file}\n"
                f"Please create it from: {self.infra_dir / 'parameters.example.yaml'}"
            )

        with open(self.parameters_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        region_id = data.get("RegionId", "cn-hangzhou")
        stack_prefix = data.get("StackNamePrefix", "haifa-eval-spot")
        params = data.get("Parameters", {})
        return region_id, stack_prefix, params

    def _run_aliyun(self, args: list[str]) -> dict[str, Any]:
        """Execute an aliyun CLI command and parse JSON output."""
        cmd = [self.aliyun_bin, *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
        )
        if result.returncode != 0:
            err_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"aliyun CLI command failed (code {result.returncode}): {err_msg}")

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw_output": result.stdout.strip()}

    def validate_template(self) -> dict[str, Any]:
        """Validate template syntax and parameter declarations."""
        region_id, _, _ = self.load_config()
        template_body = self.template_file.read_text(encoding="utf-8")
        args = [
            "ros",
            "ValidateTemplate",
            "--RegionId",
            region_id,
            "--TemplateBody",
            template_body,
        ]
        return self._run_aliyun(args)

    def create_stack(
        self,
        sync_env: bool = True,
        wait: bool = True,
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Create a new spot instance ROS stack."""
        region_id, stack_prefix, params = self.load_config()
        template_body = self.template_file.read_text(encoding="utf-8")

        timestamp = time.strftime("%Y%m%d%H%M%S")
        stack_name = f"{stack_prefix}-{timestamp}"

        cmd_args = [
            "ros",
            "CreateStack",
            "--RegionId",
            region_id,
            "--StackName",
            stack_name,
            "--TemplateBody",
            template_body,
        ]

        # Format ROS parameters: --Parameters.1.ParameterKey Key --Parameters.1.ParameterValue Val
        idx = 1
        for k, v in params.items():
            if v is not None:
                cmd_args.extend([
                    f"--Parameters.{idx}.ParameterKey",
                    str(k),
                    f"--Parameters.{idx}.ParameterValue",
                    str(v),
                ])
                idx += 1

        print(f"[ROSManager] Creating stack '{stack_name}' in region '{region_id}'...")
        res = self._run_aliyun(cmd_args)
        stack_id = res.get("StackId")
        if not stack_id:
            raise RuntimeError(f"Failed to obtain StackId from ROS response: {res}")

        print(f"[ROSManager] Stack created with ID: {stack_id}")

        # Save active stack tracking
        stack_info: dict[str, Any] = {
            "stack_id": stack_id,
            "stack_name": stack_name,
            "region_id": region_id,
            "create_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "CREATE_IN_PROGRESS",
            "instance_ids": [],
            "public_ips": [],
        }
        self._save_state(stack_info)

        if not wait:
            return stack_info

        # Poll status until complete
        print(f"[ROSManager] Waiting for stack to complete creation (timeout {timeout}s)...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            stack_details = self.get_stack(stack_id=stack_id, region_id=region_id)
            status = stack_details.get("Status", "UNKNOWN")
            reason = stack_details.get("StatusReason", "")
            print(f"  -> Status: {status} ({reason})")

            if status == "CREATE_COMPLETE":
                outputs = stack_details.get("Outputs", [])
                public_ips = []
                instance_ids = []
                for out in outputs:
                    key = out.get("OutputKey")
                    val = out.get("OutputValue")
                    if key == "PublicIps":
                        public_ips = val if isinstance(val, list) else [val]
                    elif key == "InstanceIds":
                        instance_ids = val if isinstance(val, list) else [val]

                stack_info.update({
                    "status": status,
                    "instance_ids": instance_ids,
                    "public_ips": public_ips,
                })
                self._save_state(stack_info)
                print(f"[ROSManager] Stack is ready! Public IPs: {public_ips}, Instance IDs: {instance_ids}")

                if sync_env and public_ips:
                    self._sync_env_target_ip(public_ips[0])

                return stack_info

            if "FAILED" in status or "ROLLBACK" in status:
                stack_info["status"] = status
                self._save_state(stack_info)
                raise RuntimeError(f"Stack creation failed with status: {status} - {reason}")

            time.sleep(poll_interval)

        raise TimeoutError(f"Stack creation timed out after {timeout} seconds")

    def get_stack(self, stack_id: str | None = None, region_id: str | None = None) -> dict[str, Any]:
        """Fetch stack details from ROS."""
        sid = stack_id or self._load_active_stack_id()
        if not sid:
            raise ValueError("No stack_id provided and no active stack recorded in state file.")

        reg = region_id
        if not reg:
            reg, _, _ = self.load_config()

        args = ["ros", "GetStack", "--RegionId", reg, "--StackId", sid]
        return self._run_aliyun(args)

    def delete_stack(
        self,
        stack_id: str | None = None,
        region_id: str | None = None,
        wait: bool = True,
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> None:
        """Delete a ROS stack and clean up state."""
        sid = stack_id or self._load_active_stack_id()
        if not sid:
            raise ValueError("No stack_id provided and no active stack recorded in state file.")

        reg = region_id
        if not reg:
            reg, _, _ = self.load_config()

        print(f"[ROSManager] Deleting stack: {sid} in region: {reg}...")
        args = ["ros", "DeleteStack", "--RegionId", reg, "--StackId", sid]
        self._run_aliyun(args)

        if wait:
            print("[ROSManager] Waiting for stack deletion to complete...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    res = self.get_stack(stack_id=sid, region_id=reg)
                    status = res.get("Status")
                    reason = res.get("StatusReason", "")
                    print(f"  -> Status: {status} ({reason})")
                    if status == "DELETE_COMPLETE":
                        break
                    if "FAILED" in str(status):
                        raise RuntimeError(f"Stack deletion failed with status: {status}")
                except Exception as e:
                    if "EntityNotExists" in str(e) or "StackNotFound" in str(e):
                        break
                    raise
                time.sleep(poll_interval)

        self._clear_state()
        print(f"[ROSManager] Stack {sid} deleted successfully.")

    def _sync_env_target_ip(self, ip: str) -> None:
        """Update TARGET_HOST_IP in the repo root .env file."""
        env_file = REPO_ROOT / ".env"
        if not env_file.exists():
            print(f"[ROSManager] Note: .env file does not exist at {env_file}, skipping IP sync.")
            return

        lines = env_file.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("TARGET_HOST_IP="):
                new_lines.append(f'TARGET_HOST_IP="{ip}"')
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f'TARGET_HOST_IP="{ip}"')

        env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[ROSManager] Automatically synced TARGET_HOST_IP={ip} into {env_file}")

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_active_stack_id(self) -> str | None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                return data.get("stack_id")
            except Exception:
                pass
        return None

    def _clear_state(self) -> None:
        if self.state_file.exists():
            with contextlib.suppress(OSError):
                self.state_file.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="ROS Spot Instance Stack Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    subparsers.add_parser("validate", help="Validate ROS template and parameters")

    # up
    up_parser = subparsers.add_parser("up", help="Launch preemptible (spot) instances stack")
    up_parser.add_argument("--no-wait", action="store_true", help="Do not wait for creation to complete")
    up_parser.add_argument("--no-sync-env", action="store_true", help="Do not update TARGET_HOST_IP in .env")
    up_parser.add_argument("--timeout", type=int, default=300, help="Creation timeout in seconds")

    # status
    status_parser = subparsers.add_parser("status", help="Get current stack status")
    status_parser.add_argument("--stack-id", help="Stack ID (defaults to active stack)")

    # down
    down_parser = subparsers.add_parser("down", help="Delete preemptible stack")
    down_parser.add_argument("--stack-id", help="Stack ID (defaults to active stack)")
    down_parser.add_argument("--no-wait", action="store_true", help="Do not wait for deletion to complete")

    args = parser.parse_args()
    mgr = ROSManager()

    if args.command == "validate":
        res = mgr.validate_template()
        print("[ROSManager] Template validation successful:")
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "up":
        info = mgr.create_stack(
            sync_env=not args.no_sync_env,
            wait=not args.no_wait,
            timeout=args.timeout,
        )
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif args.command == "status":
        info = mgr.get_stack(stack_id=args.stack_id)
        print(json.dumps(info, indent=2, ensure_ascii=False))

    elif args.command == "down":
        mgr.delete_stack(stack_id=args.stack_id, wait=not args.no_wait)


if __name__ == "__main__":
    main()
