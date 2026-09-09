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
