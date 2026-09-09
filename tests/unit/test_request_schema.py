"""Tests for Run Request V1 schema validation and canonical hashing."""

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
    assert len(sha) == 64
    assert canonical_json(req.model_dump()) == canonical_str


def test_commit_must_be_40_char_hex(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))

    # Test invalid short commit
    invalid_raw = copy.deepcopy(raw)
    invalid_raw["source"]["repositories"]["product"]["commit"] = "main"
    with pytest.raises(RequestValidationError, match="exact 40-character hex SHA"):
        RunRequest.model_validate(invalid_raw)

    # Test invalid branch or non-hex
    invalid_raw["source"]["repositories"]["product"]["commit"] = (
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


def test_duplicate_run_ids_forbidden(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["evaluation"]["runs"].append(copy.deepcopy(raw["evaluation"]["runs"][0]))
    with pytest.raises(RequestValidationError, match="Duplicate run IDs"):
        RunRequest.model_validate(raw)


def test_invalid_run_id_characters(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["runId"] = "run with spaces"
    with pytest.raises(RequestValidationError, match="runId must match"):
        RunRequest.model_validate(raw)


def test_repo_branch_only_is_valid(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    del raw["source"]["repositories"]["product"]["commit"]
    raw["source"]["repositories"]["product"]["branch"] = "main"

    req = RunRequest.model_validate(raw)
    assert req.source.repositories.product.branch == "main"
    assert req.source.repositories.product.commit == ""
    assert req.source.repositories.product.target_ref == "main"


def test_repo_commit_takes_precedence_over_branch(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["source"]["repositories"]["product"]["branch"] = "main"
    # commit is already 40-char hex
    req = RunRequest.model_validate(raw)
    assert req.source.repositories.product.branch == "main"
    assert req.source.repositories.product.commit == "0123456789abcdef0123456789abcdef01234567"
    assert req.source.repositories.product.target_ref == "0123456789abcdef0123456789abcdef01234567"


def test_repo_neither_commit_nor_branch_fails(sample_request_path: Path):
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    del raw["source"]["repositories"]["product"]["commit"]
    # Neither commit nor branch
    with pytest.raises(RequestValidationError, match="must specify either 'commit' .* or 'branch'"):
        RunRequest.model_validate(raw)
