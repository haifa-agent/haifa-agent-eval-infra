"""Tests for SSHTransport command generation and strict flags."""

from __future__ import annotations

from pathlib import Path

from evalctl.transport.ssh import SSHTransport


def test_ssh_base_args_include_security_flags(tmp_path: Path):
    key_file = tmp_path / "id_rsa"
    key_file.write_text("fake-key", encoding="utf-8")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("fake-host", encoding="utf-8")

    transport = SSHTransport(
        host="203.0.113.10",
        user="eval-admin",
        key_path=key_file,
        port=2222,
        known_hosts_path=known_hosts,
    )

    args = transport._base_ssh_args()
    assert "-p" in args and "2222" in args
    assert "-i" in args and str(key_file) in args
    assert "-o" in args and "BatchMode=yes" in args
    assert "IdentitiesOnly=yes" in args
    assert "StrictHostKeyChecking=yes" in args
    assert f"UserKnownHostsFile={known_hosts}" in args
    assert "eval-admin@203.0.113.10" in args
