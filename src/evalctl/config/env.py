"""Loader for local .env credential and configuration files."""

from __future__ import annotations

import os
from pathlib import Path

from evalctl.core.errors import EvalctlError


def parse_env_content(content: str) -> dict[str, str]:
    """Parses .env string content into a dictionary of key-value pairs."""
    vars_dict: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        vars_dict[key] = val
    return vars_dict


def load_env_file(
    env_file_path: Path | str | None = None,
    *,
    override: bool = True,
) -> Path | None:
    """Loads environment variables from a .env file into os.environ.

    - If env_file_path is explicitly provided, it MUST exist, otherwise raises EvalctlError.
    - If env_file_path is None, defaults to looking for '.env' in current working directory.
      If it exists, loads it; if not, safely does nothing.
    """
    if env_file_path is not None:
        target_path = Path(env_file_path).resolve()
        if not target_path.is_file():
            raise EvalctlError(f"Specified --env-file not found: {target_path}")
    else:
        target_path = Path.cwd() / ".env"
        if not target_path.is_file():
            return None

    try:
        content = target_path.read_text(encoding="utf-8")
        parsed_vars = parse_env_content(content)
        for key, value in parsed_vars.items():
            if override or key not in os.environ:
                os.environ[key] = value
        return target_path
    except Exception as exc:
        raise EvalctlError(f"Failed to read .env file at {target_path}: {exc}") from exc
