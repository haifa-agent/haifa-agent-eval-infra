"""Tests for .env file loader and CLI integration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evalctl.cli import main
from evalctl.config.env import load_env_file, parse_env_content
from evalctl.core.errors import EvalctlError


def test_parse_env_content():
    content = """
    # Comment line
    FOO=bar
    BAZ="quoted value"
    SPACED = 'single quoted'
    EMPTY=
    INVALID_LINE_WITHOUT_EQUALS
    """
    vars_dict = parse_env_content(content)
    assert vars_dict["FOO"] == "bar"
    assert vars_dict["BAZ"] == "quoted value"
    assert vars_dict["SPACED"] == "single quoted"
    assert vars_dict["EMPTY"] == ""
    assert "INVALID_LINE_WITHOUT_EQUALS" not in vars_dict


def test_load_env_file_explicit_path(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TEST_KEY_EXPLICIT", raising=False)
    env_file = tmp_path / "custom.env"
    env_file.write_text("TEST_KEY_EXPLICIT=hello_world\n", encoding="utf-8")

    loaded = load_env_file(env_file)
    assert loaded == env_file
    assert os.getenv("TEST_KEY_EXPLICIT") == "hello_world"


def test_load_env_file_explicit_missing_raises_error(tmp_path: Path):
    missing_file = tmp_path / "nonexistent.env"
    with pytest.raises(EvalctlError, match="Specified --env-file not found"):
        load_env_file(missing_file)


def test_load_env_file_default_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TEST_KEY_DEFAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    dot_env = tmp_path / ".env"
    dot_env.write_text("TEST_KEY_DEFAULT=from_default_dotenv\n", encoding="utf-8")

    loaded = load_env_file(None)
    assert loaded == dot_env
    assert os.getenv("TEST_KEY_DEFAULT") == "from_default_dotenv"


def test_cli_accepts_env_file(sample_request_path: Path, tmp_path: Path, monkeypatch):
    env_file = tmp_path / "test.env"
    env_file.write_text("MY_CUSTOM_VAR=123\n", encoding="utf-8")

    ret = main(
        ["--env-file", str(env_file), "request", "validate", "--file", str(sample_request_path)]
    )
    assert ret == 0
    assert os.getenv("MY_CUSTOM_VAR") == "123"


def test_target_ip_and_user_from_env(tmp_path: Path, monkeypatch):
    from evalctl.config.loader import load_run_request

    monkeypatch.setenv("TARGET_HOST_IP", "10.0.0.99")
    monkeypatch.delenv("TARGET_HOST_USER", raising=False)

    yaml_content = """
schemaVersion: 1
runId: test-run-ip-user
target:
  sshPrivateKeyFileEnv: DUMMY_KEY_ENV
source:
  githubPrivateKeyFileEnv: DUMMY_GH_ENV
  repositories:
    product: { url: "a", commit: "0123456789abcdef0123456789abcdef01234567" }
    docs: { url: "b", commit: "1123456789abcdef0123456789abcdef01234567" }
    testConfig: { url: "c", commit: "2123456789abcdef0123456789abcdef01234567" }
evaluation:
  kind: haifa-harness
  providerId: zhipu
  modelId: glm-5.3-flash
  agentProfileRef: test-prof
output:
  localResultRoot: D:/test-results
"""
    req_file = tmp_path / "req.yaml"
    req_file.write_text(yaml_content, encoding="utf-8")

    req, _, _ = load_run_request(
        req_file, validate_local_keys=False, validate_local_result_root=False
    )
    assert req.target.address == "10.0.0.99"
    assert req.target.user == "ecs-user"  # Default user


def test_target_yaml_env_placeholder_expansion(tmp_path: Path, monkeypatch):
    from evalctl.config.loader import load_run_request

    monkeypatch.setenv("MY_IP", "172.16.0.5")
    monkeypatch.setenv("MY_USER", "custom-admin")

    yaml_content = """
schemaVersion: 1
runId: test-run-expansion
target:
  address: "${MY_IP}"
  user: "${MY_USER:-default-user}"
  sshPrivateKeyFileEnv: DUMMY_KEY_ENV
source:
  githubPrivateKeyFileEnv: DUMMY_GH_ENV
  repositories:
    product: { url: "a", commit: "0123456789abcdef0123456789abcdef01234567" }
    docs: { url: "b", commit: "1123456789abcdef0123456789abcdef01234567" }
    testConfig: { url: "c", commit: "2123456789abcdef0123456789abcdef01234567" }
evaluation:
  kind: haifa-harness
  providerId: zhipu
  modelId: glm-5.3-flash
  agentProfileRef: test-prof
output:
  localResultRoot: D:/test-results
"""
    req_file = tmp_path / "req2.yaml"
    req_file.write_text(yaml_content, encoding="utf-8")

    req, _, _ = load_run_request(
        req_file, validate_local_keys=False, validate_local_result_root=False
    )
    assert req.target.address == "172.16.0.5"
    assert req.target.user == "custom-admin"
