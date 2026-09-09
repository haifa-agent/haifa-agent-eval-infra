"""Loader and canonical digest generator for Run Request YAML files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from evalctl.config.schema import RunRequest
from evalctl.core.errors import RequestValidationError


def canonical_json(data: dict[str, Any]) -> str:
    """Serializes a dictionary to deterministic, canonical JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calculate_sha256(content: str | bytes) -> str:
    """Calculates hex SHA-256 digest."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def check_key_file(env_name: str, purpose: str) -> Path:
    """Verifies that the private key file referenced by an environment variable exists."""
    path_str = os.getenv(env_name)
    if not path_str:
        raise RequestValidationError(
            f"Environment variable '{env_name}' for {purpose} is not set in local environment"
        )
    key_path = Path(path_str).resolve()
    if not key_path.is_file():
        raise RequestValidationError(
            f"Private key file for {purpose} does not exist: {key_path} (from {env_name})"
        )

    # On POSIX, check permissions are not group/world readable
    if os.name == "posix":
        mode = key_path.stat().st_mode & 0o777
        if mode & 0o077:
            raise RequestValidationError(
                f"Private key file {key_path} has insecure permissions {oct(mode)}; expected 0600"
            )
    return key_path


def load_run_request(
    file_path: Path | str,
    *,
    validate_local_keys: bool = True,
    validate_local_result_root: bool = True,
) -> tuple[RunRequest, str, str]:
    """Loads, validates, and computes the canonical SHA-256 of a Run Request YAML."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise RequestValidationError(f"Run Request file not found: {path}")

    try:
        raw_content = path.read_text(encoding="utf-8")
        parsed_data = yaml.safe_load(raw_content)
    except Exception as exc:
        raise RequestValidationError(f"Failed to parse YAML file {path}: {exc}") from exc

    if not isinstance(parsed_data, dict):
        raise RequestValidationError(
            f"Run Request YAML must define a mapping, got: {type(parsed_data)}"
        )

    try:
        request = RunRequest.model_validate(parsed_data)
    except ValidationError as exc:
        raise RequestValidationError(f"Run Request validation failed: {exc}") from exc

    canonical_str = canonical_json(request.model_dump())
    request_sha256 = calculate_sha256(canonical_str)

    if validate_local_keys:
        check_key_file(request.target.sshPrivateKeyFileEnv, "Host SSH Key")
        check_key_file(request.source.githubPrivateKeyFileEnv, "GitHub Deploy Key")

    if validate_local_result_root:
        result_root = Path(request.output.localResultRoot).resolve()
        # Ensure localResultRoot is not inside a git repo
        current = result_root
        while current != current.parent:
            if (current / ".git").exists():
                raise RequestValidationError(
                    f"localResultRoot ({result_root}) must not be inside a Git repository ({current})"
                )
            current = current.parent

    return request, canonical_str, request_sha256
