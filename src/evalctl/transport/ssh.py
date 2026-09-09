import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from evalctl.core.errors import EvalctlError


def find_ssh_binary(name: str) -> str:
    """Finds the best available OpenSSH binary, preferring modern Git OpenSSH on Windows."""
    if os.name == "nt":
        git_usr_bin = Path(r"C:\Program Files\Git\usr\bin") / f"{name}.exe"
        if git_usr_bin.is_file():
            return str(git_usr_bin)
    return shutil.which(name) or name


class SSHTransport:
    """Safe OpenSSH wrapper enforcing security constraints."""

    def __init__(
        self,
        host: str,
        user: str,
        key_path: Path,
        port: int = 22,
        known_hosts_path: Path | None = None,
        connect_timeout: int = 15,
    ) -> None:
        self.host = host
        self.user = user
        self.key_path = key_path
        self.port = port
        self.known_hosts_path = known_hosts_path
        self.connect_timeout = connect_timeout

    def _base_ssh_args(self) -> list[str]:
        args = [
            find_ssh_binary("ssh"),
            "-p",
            str(self.port),
            "-i",
            str(self.key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
        ]
        if self.known_hosts_path:
            args.extend(
                [
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={self.known_hosts_path}",
                ]
            )
        else:
            args.extend(["-o", "StrictHostKeyChecking=ask"])
        args.append(f"{self.user}@{self.host}")
        return args

    def run_command(
        self,
        remote_args: list[str],
        *,
        stdin_data: str | bytes | None = None,
        timeout: int | None = 60,
        verbose: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Executes a command remotely via parameter list (no raw shell string concatenation)."""
        quoted_args = [shlex.quote(arg) for arg in remote_args]
        cmd = self._base_ssh_args() + ["--"] + quoted_args
        stdin_bytes = None
        if stdin_data is not None:
            if isinstance(stdin_data, str):
                stdin_bytes = stdin_data.replace("\r\n", "\n").encode("utf-8")
            else:
                stdin_bytes = stdin_data.replace(b"\r\n", b"\n")

        try:
            if not verbose:
                res = subprocess.run(
                    cmd,
                    input=stdin_bytes,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
                return subprocess.CompletedProcess(
                    args=res.args,
                    returncode=res.returncode,
                    stdout=res.stdout.decode("utf-8", errors="replace"),
                    stderr=res.stderr.decode("utf-8", errors="replace"),
                )

            # Live streaming mode when verbose=True
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_bytes is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if stdin_bytes is not None and proc.stdin:
                proc.stdin.write(stdin_bytes)
                proc.stdin.close()

            stdout_chunks: list[str] = []
            if proc.stdout:
                for line_bytes in iter(proc.stdout.readline, b""):
                    line_str = line_bytes.decode("utf-8", errors="replace")
                    print(line_str, end="", flush=True)
                    stdout_chunks.append(line_str)

            ret = proc.wait(timeout=timeout)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=ret,
                stdout="".join(stdout_chunks),
                stderr="",
            )
        except subprocess.TimeoutExpired as exc:
            raise EvalctlError(
                f"SSH command timed out after {timeout}s: {' '.join(remote_args)}"
            ) from exc
        except Exception as exc:
            raise EvalctlError(f"SSH transport execution failed: {exc}") from exc

    def upload_file(self, local_path: Path, remote_path: str) -> None:
        """Copies a local file to the remote host using scp."""
        scp_args = [
            find_ssh_binary("scp"),
            "-P",
            str(self.port),
            "-i",
            str(self.key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
        ]
        if self.known_hosts_path:
            scp_args.extend(
                [
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={self.known_hosts_path}",
                ]
            )
        scp_args.extend([str(local_path), f"{self.user}@{self.host}:{remote_path}"])
        result = subprocess.run(scp_args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise EvalctlError(f"SCP upload failed ({result.returncode}): {result.stderr.strip()}")

    def download_file(self, remote_path: str, local_path: Path) -> None:
        """Copies a remote file to the local host using scp."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        scp_args = [
            find_ssh_binary("scp"),
            "-P",
            str(self.port),
            "-i",
            str(self.key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
        ]
        if self.known_hosts_path:
            scp_args.extend(
                [
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={self.known_hosts_path}",
                ]
            )
        scp_args.extend([f"{self.user}@{self.host}:{remote_path}", str(local_path)])
        result = subprocess.run(scp_args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise EvalctlError(
                f"SCP download failed ({result.returncode}): {result.stderr.strip()}"
            )

    def stream_command(
        self,
        remote_args: list[str],
        on_line: Callable[[str], None],
        *,
        timeout: int | None = None,
    ) -> int:
        """Executes a command and streams output line by line."""
        quoted_args = [shlex.quote(arg) for arg in remote_args]
        cmd = self._base_ssh_args() + ["--"] + quoted_args
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        if process.stdout is None:
            raise EvalctlError("SSH process stdout unavailable")

        try:
            for line in process.stdout:
                on_line(line)
            return process.wait(timeout=timeout)
        except Exception:
            process.kill()
            raise
