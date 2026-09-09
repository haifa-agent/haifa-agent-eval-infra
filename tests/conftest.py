"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_request_path() -> Path:
    return REPO_ROOT / "tests" / "fixtures" / "sample_request.yaml"


@pytest.fixture
def temp_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "test-run-001"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
