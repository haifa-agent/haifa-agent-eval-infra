"""Tests for Host Key parsing and verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from evalctl.config.loader import load_run_request
from evalctl.core.errors import HostTrustError
from evalctl.host.trust import parse_host_key_fingerprint, verify_host_key


def test_parse_host_key_fingerprint():
    # Example RSA line with base64 data
    line = "203.0.113.10 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAG9u8aNfqH/oGzB1y0y7qU+t7f3XkM3o5p1y4l8qZpA"
    ktype, fp = parse_host_key_fingerprint(line)
    assert ktype == "ssh-ed25519"
    assert fp.startswith("SHA256:")


def test_verify_host_key_mismatch_raises_error(
    sample_request_path: Path, monkeypatch, tmp_path: Path
):
    req, _, _ = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )

    # Mock scan_remote_host_key to return a different fingerprint
    fake_key_line = "203.0.113.10 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAG9u8aNfqH/oGzB1y0y7qU+t7f3XkM3o5p1y4l8qZpA"
    monkeypatch.setattr(
        "evalctl.host.trust.scan_remote_host_key",
        lambda addr, port: [(fake_key_line, "ssh-ed25519", "SHA256:differentFingerprint")],
    )

    known_hosts = tmp_path / "known_hosts"
    with pytest.raises(HostTrustError, match="Host key mismatch"):
        verify_host_key(req, known_hosts)
