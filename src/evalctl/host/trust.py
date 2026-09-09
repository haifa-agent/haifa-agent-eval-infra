"""SSH Host Key verification and fingerprint management."""

from __future__ import annotations

import base64
import hashlib
import subprocess
from pathlib import Path

from evalctl.config.schema import RunRequest
from evalctl.core.errors import HostTrustError
from evalctl.transport.ssh import find_ssh_binary


def parse_host_key_fingerprint(raw_key_line: str) -> tuple[str, str]:
    """Extracts algorithm and SHA256 fingerprint from an OpenSSH host key line."""
    parts = raw_key_line.strip().split()
    if len(parts) < 3:
        raise HostTrustError(f"Malformed host key line: {raw_key_line}")
    key_type = parts[1]
    raw_bytes = base64.b64decode(parts[2])
    digest = hashlib.sha256(raw_bytes).digest()
    fingerprint = "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
    return key_type, fingerprint


def scan_remote_host_key(address: str, port: int = 22) -> list[tuple[str, str, str]]:
    """Runs ssh-keyscan to discover host keys and returns list of (line, type, fingerprint)."""
    cmd = [find_ssh_binary("ssh-keyscan"), "-p", str(port), address]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except Exception as exc:
        raise HostTrustError(f"Failed to scan host key for {address}:{port}: {exc}") from exc

    results: list[tuple[str, str, str]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            ktype, fp = parse_host_key_fingerprint(line)
            results.append((line, ktype, fp))
        except Exception:
            continue

    if not results:
        raise HostTrustError(f"No valid host keys found from {address}:{port}")
    return results


def verify_host_key(
    request: RunRequest,
    known_hosts_out_path: Path,
) -> str:
    """Verifies that the remote host key matches request.target.hostKeySha256.

    If request.target.hostKeySha256 is empty, prints the discovered fingerprint
    and raises HostTrustError to ensure explicit human freezing before proceeding.
    """
    keys = scan_remote_host_key(request.target.address, request.target.port)
    expected_fp = request.target.hostKeySha256.strip()

    if not expected_fp:
        fps_str = ", ".join(f"[{ktype}] {fp}" for _, ktype, fp in keys)
        raise HostTrustError(
            f"Host key is not frozen in Run Request. Discovered host keys:\n  {fps_str}\n"
            f"Action required: Copy the approved fingerprint into request.target.hostKeySha256"
        )

    matched_line: str | None = None
    for line, _, fp in keys:
        if fp == expected_fp:
            matched_line = line
            break

    if not matched_line:
        found_fps = [fp for _, _, fp in keys]
        raise HostTrustError(
            f"Host key mismatch for {request.target.address}:{request.target.port}!\n"
            f"  Expected: {expected_fp}\n"
            f"  Discovered: {found_fps}\n"
            f"FAIL-CLOSED: Connection aborted due to potential man-in-the-middle or host change."
        )

    # Write approved host key to isolated known_hosts
    known_hosts_out_path.parent.mkdir(parents=True, exist_ok=True)
    known_hosts_out_path.write_text(matched_line + "\n", encoding="utf-8")
    return expected_fp
