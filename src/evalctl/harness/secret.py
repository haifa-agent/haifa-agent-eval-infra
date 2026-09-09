"""Secure injection and disposal of API keys into remote tmpfs."""

from __future__ import annotations

import os

from evalctl.config.schema import RunRequest
from evalctl.core.errors import EvalctlError
from evalctl.transport.ssh import SSHTransport


class EphemeralSecretManager:
    """Manages ephemeral secret lifecycle in /run tmpfs."""

    def __init__(self, transport: SSHTransport, request: RunRequest) -> None:
        self.transport = transport
        self.request = request
        self.remote_dir = f"/run/haifa-eval/{request.runId}"
        self.remote_file = f"{self.remote_dir}/secrets.env"

    def inject_secrets(self) -> str:
        """Injects secrets from local environment into remote tmpfs via stdin."""
        # 1. Confirm /run is tmpfs on remote
        res = self.transport.run_command(["df", "-T", "/run"])
        if "tmpfs" not in res.stdout:
            raise EvalctlError("Remote /run is not a tmpfs mount; refusing to inject secrets")

        # 2. Gather secrets from local env
        lines: list[str] = []
        for name in self.request.evaluation.requiredSecretEnvironmentNames:
            val = os.getenv(name)
            if val is not None:
                # Format as KEY="VALUE" escaping internal quotes
                escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{name}="{escaped}"')

        content = "\n".join(lines) + "\n"

        # 3. Create directory and write file securely with 0600 permissions
        script = (
            f"set -eu\n"
            f"mkdir -p {self.remote_dir}\n"
            f"cat << 'EOF_SECRETS' > {self.remote_file}\n"
            f"{content}"
            f"EOF_SECRETS\n"
            f"chown -R haifa-eval:haifa-eval {self.remote_dir}\n"
            f"chmod 0700 {self.remote_dir}\n"
            f"chmod 0600 {self.remote_file}\n"
        )
        res_inject = self.transport.run_command(
            ["sudo", "bash", "-s"], stdin_data=script, timeout=15
        )
        if res_inject.returncode != 0:
            raise EvalctlError(f"Failed to inject secrets to remote tmpfs: {res_inject.stderr}")

        return self.remote_file

    def destroy_secrets(self) -> None:
        """Destroys ephemeral secrets file and directory."""
        self.transport.run_command(
            ["sudo", "rm", "-rf", self.remote_dir],
            timeout=10,
        )
