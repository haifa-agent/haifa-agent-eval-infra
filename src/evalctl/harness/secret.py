"""Secure injection and disposal of provider keys and the GitHub deploy key into remote tmpfs."""

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
        self.github_key_file = f"{self.remote_dir}/github.key"

    def _read_github_key(self) -> str:
        key_env = self.request.source.githubPrivateKeyFileEnv
        key_path_str = os.getenv(key_env)
        if not key_path_str:
            raise EvalctlError(f"GitHub deploy key env var '{key_env}' is not set")
        key_path = os.path.abspath(key_path_str.strip().strip("\"'"))
        if not os.path.isfile(key_path):
            raise EvalctlError(f"GitHub deploy key file not found: {key_path}")
        with open(key_path, encoding="utf-8") as stream:
            content = stream.read()
        if not content.endswith("\n"):
            content += "\n"
        return content

    def inject_secrets(self) -> str:
        """Injects provider secrets and the GitHub deploy key into remote tmpfs via stdin."""
        # 1. Confirm /run is tmpfs on remote
        res = self.transport.run_command(["df", "-T", "/run"])
        if "tmpfs" not in res.stdout:
            raise EvalctlError("Remote /run is not a tmpfs mount; refusing to inject secrets")

        # 2. Gather provider secrets from local env (fail-closed if any are missing)
        lines: list[str] = []
        for name in self.request.evaluation.requiredSecretEnvironmentNames:
            val = os.getenv(name)
            if not val:
                raise EvalctlError(
                    f"Required provider secret environment variable '{name}' is not set locally"
                )
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{name}="{escaped}"')

        github_key = self._read_github_key()
        git_ssh_command = (
            f"ssh -i {self.github_key_file} -o IdentitiesOnly=yes "
            "-o BatchMode=yes -o StrictHostKeyChecking=accept-new"
        )
        lines.append(f'GIT_SSH_COMMAND="{git_ssh_command}"')
        content = "\n".join(lines) + "\n"

        # 3. Create the run secret directory on tmpfs
        res_dir = self.transport.run_command(
            ["sudo", "bash", "-c", f"mkdir -p {self.remote_dir} && chmod 0700 {self.remote_dir}"],
            timeout=15,
        )
        if res_dir.returncode != 0:
            raise EvalctlError(f"Failed to create remote secret directory: {res_dir.stderr}")

        # 4. Write the GitHub deploy key (0600, owned by haifa-eval)
        res_key = self.transport.run_command(
            [
                "sudo",
                "bash",
                "-c",
                f"cat > {self.github_key_file} && chmod 0600 {self.github_key_file} "
                f"&& chown haifa-eval:haifa-eval {self.github_key_file}",
            ],
            stdin_data=github_key,
            timeout=15,
        )
        if res_key.returncode != 0:
            raise EvalctlError(f"Failed to inject GitHub deploy key: {res_key.stderr}")

        # 5. Write the secrets.env file (0600, owned by haifa-eval)
        res_env = self.transport.run_command(
            [
                "sudo",
                "bash",
                "-c",
                f"cat > {self.remote_file} && chmod 0600 {self.remote_file} "
                f"&& chown -R haifa-eval:haifa-eval {self.remote_dir}",
            ],
            stdin_data=content,
            timeout=15,
        )
        if res_env.returncode != 0:
            raise EvalctlError(f"Failed to inject secrets to remote tmpfs: {res_env.stderr}")

        return self.remote_file

    def destroy_secrets(self) -> None:
        """Destroys ephemeral secret files and directory."""
        self.transport.run_command(
            ["sudo", "rm", "-rf", self.remote_dir],
            timeout=10,
        )
