"""Tests for Run Request V2 schema validation and canonical hashing."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from evalctl.config.loader import canonical_json, load_run_request
from evalctl.config.schema import RunRequest
from evalctl.core.errors import RequestValidationError


def test_valid_sample_request_loads_successfully(sample_request_path: Path):
    req, canonical_str, sha = load_run_request(
        sample_request_path, validate_local_keys=False, validate_local_result_root=False
    )
    assert req.runId == "zhipu-glm53-ubuntu-20260909-001"
    assert req.target.address == "203.0.113.10"
    assert req.evaluation.modelId == "glm-5.3-flash"
    assert req.evaluation.kind == "haifa-ladder"
    assert req.evaluation.caseSet == "ladder-v1"
    assert len(sha) == 64
    assert canonical_json(req.model_dump()) == canonical_str


def test_schema_version_must_be_2(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["schemaVersion"] = 1
    with pytest.raises(RequestValidationError, match="only supports version 2"):
        RunRequest.model_validate(raw)


def test_commit_must_be_40_char_hex(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))

    invalid_raw = copy.deepcopy(raw)
    invalid_raw["source"]["product"]["commit"] = "main"
    with pytest.raises(RequestValidationError, match="exact 40-character hex SHA"):
        RunRequest.model_validate(invalid_raw)

    invalid_raw["source"]["product"]["commit"] = (
        "0123456789abcdef0123456789abcdef0123456z"
    )
    with pytest.raises(RequestValidationError, match="exact 40-character hex SHA"):
        RunRequest.model_validate(invalid_raw)


def test_host_key_and_github_key_env_must_differ(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["source"]["githubPrivateKeyFileEnv"] = "SAME_KEY_ENV"
    raw["target"]["sshPrivateKeyFileEnv"] = "SAME_KEY_ENV"
    with pytest.raises(RequestValidationError, match="must be distinct environment variables"):
        RunRequest.model_validate(raw)


def test_invalid_run_id_characters(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["runId"] = "run with spaces"
    with pytest.raises(RequestValidationError, match="runId must match"):
        RunRequest.model_validate(raw)


def test_repo_branch_only_is_valid(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    del raw["source"]["product"]["commit"]
    raw["source"]["product"]["branch"] = "main"

    req = RunRequest.model_validate(raw)
    assert req.source.product.branch == "main"
    assert req.source.product.commit == ""
    assert req.source.product.target_ref == "main"


def test_repo_commit_takes_precedence_over_branch(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["source"]["product"]["branch"] = "main"
    req = RunRequest.model_validate(raw)
    assert req.source.product.branch == "main"
    assert req.source.product.commit == "0123456789abcdef0123456789abcdef01234567"
    assert req.source.product.target_ref == "0123456789abcdef0123456789abcdef01234567"


def test_repo_neither_commit_nor_branch_fails(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    del raw["source"]["product"]["commit"]
    with pytest.raises(RequestValidationError, match="must specify either 'commit' .* or 'branch'"):
        RunRequest.model_validate(raw)


def test_evaluation_paths_must_be_absolute(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["evaluation"]["agentDistributionDir"] = "relative/path"
    with pytest.raises(RequestValidationError, match="must be absolute"):
        RunRequest.model_validate(raw)


def test_repeat_must_be_positive(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["evaluation"]["repeat"] = 0
    with pytest.raises(RequestValidationError, match="repeat must be >= 1"):
        RunRequest.model_validate(raw)
