"""Pydantic schema definitions for Run Request V2 (autonomous-delivery ladder runner)."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from evalctl.core.errors import RequestValidationError

HEX_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def _default_user() -> str:
    u = os.getenv("TARGET_HOST_USER", os.getenv("HAIFA_EVAL_TARGET_USER", "root")).strip()
    return u or "root"


class TargetConfig(BaseModel):
    address: str = Field(
        default_factory=lambda: os.getenv("TARGET_HOST_IP", os.getenv("HAIFA_EVAL_TARGET_IP", "")),
        validate_default=True,
    )
    port: int = 22
    user: str = Field(
        default_factory=_default_user,
        validate_default=True,
    )
    hostKeySha256: str = ""
    sshPrivateKeyFileEnv: str
    requirePasswordlessSudo: bool = True

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        val = value.strip() if value else ""
        if not val:
            val = os.getenv("TARGET_HOST_IP", os.getenv("HAIFA_EVAL_TARGET_IP", "")).strip()
        if not val:
            raise RequestValidationError(
                "Target host IP address is missing! Specify target.address in YAML or TARGET_HOST_IP in .env"
            )
        return val

    @field_validator("user")
    @classmethod
    def validate_user(cls, value: str) -> str:
        val = value.strip() if value else ""
        if not val:
            val = os.getenv("TARGET_HOST_USER", os.getenv("HAIFA_EVAL_TARGET_USER", "root")).strip()
        return val or "root"

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not (1 <= value <= 65535):
            raise RequestValidationError(f"Target port {value} out of range (1-65535)")
        return value

    @field_validator("hostKeySha256")
    @classmethod
    def validate_host_key(cls, value: str) -> str:
        if value and not value.startswith("SHA256:"):
            raise RequestValidationError("hostKeySha256 must start with 'SHA256:' or be empty")
        return value


class RepoSpec(BaseModel):
    url: str
    commit: str = ""
    branch: str = ""

    @model_validator(mode="after")
    def validate_commit_or_branch(self) -> RepoSpec:
        c = (self.commit or "").strip().lower()
        b = (self.branch or "").strip()
        if c:
            if not HEX_SHA_REGEX.match(c):
                raise RequestValidationError(
                    f"Repository commit must be an exact 40-character hex SHA, got: {c}"
                )
            self.commit = c
        elif b:
            self.branch = b
        else:
            raise RequestValidationError(
                f"Repository '{self.url}' must specify either 'commit' (40-char hex) or 'branch'"
            )
        return self

    @property
    def target_ref(self) -> str:
        """Returns commit if specified, otherwise branch."""
        return self.commit if self.commit else self.branch


class SourceConfig(BaseModel):
    """Only the product repository is frozen; the runner fetches case assets itself."""

    githubPrivateKeyFileEnv: str
    product: RepoSpec


class EvaluationConfig(BaseModel):
    """Autonomous-delivery capability ladder evaluation configuration."""

    kind: Literal["haifa-ladder"] = "haifa-ladder"
    providerId: str
    modelId: str
    caseSet: str = "ladder-v1"
    cases: str = ""
    repeat: int | None = None
    timeoutScale: float = 1.0
    approval: Literal["auto", "deny"] = "auto"
    allowRealProvider: bool = False
    rehearse: bool = False
    agentDistributionDir: str = "/var/lib/haifa-eval/agent-dist"
    assetsCacheDir: str = "/var/lib/haifa-eval/cache/autonomous-delivery-assets"
    requiredSecretEnvironmentNames: list[str] = Field(default_factory=list)

    @field_validator("caseSet")
    @classmethod
    def validate_case_set(cls, value: str) -> str:
        val = value.strip() if value else ""
        if not val:
            raise RequestValidationError("evaluation.caseSet must not be empty")
        return val

    @field_validator("repeat")
    @classmethod
    def validate_repeat(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise RequestValidationError("evaluation.repeat must be >= 1 when specified")
        return value

    @field_validator("timeoutScale")
    @classmethod
    def validate_timeout_scale(cls, value: float) -> float:
        if value <= 0:
            raise RequestValidationError("evaluation.timeoutScale must be > 0")
        return value

    @field_validator("agentDistributionDir", "assetsCacheDir")
    @classmethod
    def validate_absolute_path(cls, value: str) -> str:
        val = (value or "").strip()
        if not val.startswith("/"):
            raise RequestValidationError(f"Evaluation path must be absolute on the remote host: {val}")
        return val.rstrip("/") or "/"


class OutputConfig(BaseModel):
    remoteEvidenceRoot: str = "/var/lib/haifa-eval/evidence"
    localResultRoot: str
    retainRemoteEvidenceAfterPull: bool = True


class RunRequest(BaseModel):
    schemaVersion: int = 2
    runId: str
    target: TargetConfig
    source: SourceConfig
    evaluation: EvaluationConfig
    output: OutputConfig

    @field_validator("schemaVersion")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 2:
            raise RequestValidationError(
                f"Unsupported schemaVersion {value}; this control plane only supports version 2 "
                "(autonomous-delivery ladder runner)"
            )
        return value

    @field_validator("runId")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not RUN_ID_REGEX.match(value):
            raise RequestValidationError(f"runId must match {RUN_ID_REGEX.pattern}, got: {value}")
        return value

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> RunRequest:
        # Rule: Host SSH key env var must not equal GitHub deploy key env var
        if self.target.sshPrivateKeyFileEnv == self.source.githubPrivateKeyFileEnv:
            raise RequestValidationError(
                "Host SSH key env and GitHub deploy key env must be distinct environment variables"
            )
        return self
