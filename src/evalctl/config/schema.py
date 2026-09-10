"""Pydantic schema definitions for Run Request V1."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from evalctl.core.errors import RequestValidationError

HEX_SHA_REGEX = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def _default_user() -> str:
    u = os.getenv("TARGET_HOST_USER", os.getenv("HAIFA_EVAL_TARGET_USER", "ecs-user")).strip()
    return "ecs-user" if u in ("ecs-users", "ecs-user") else (u or "ecs-user")


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
            val = os.getenv(
                "TARGET_HOST_USER", os.getenv("HAIFA_EVAL_TARGET_USER", "ecs-user")
            ).strip()
        if val in ("ecs-users", "ecs-user"):
            return "ecs-user"
        return val or "ecs-user"

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


class RepositoriesConfig(BaseModel):
    product: RepoSpec
    docs: RepoSpec
    testConfig: RepoSpec


class SourceConfig(BaseModel):
    githubPrivateKeyFileEnv: str
    repositories: RepositoriesConfig


class SuiteRunSpec(BaseModel):
    id: str
    suite: str
    platform: str
    approveBudget: str
    reportRole: Literal["admission", "formal"] = "formal"


class SidecarConfig(BaseModel):
    name: str
    port: int
    healthPath: str = "/actuator/health"
    serviceName: str | None = None
    required: bool = True


class EvaluationConfig(BaseModel):
    kind: Literal["haifa-harness", "haifa-evals-harbor"] = "haifa-harness"
    providerId: str
    modelId: str
    agentProfileRef: str
    requiredSecretEnvironmentNames: list[str] = Field(default_factory=list)
    sidecars: list[SidecarConfig] = Field(default_factory=list)
    runs: list[SuiteRunSpec] = Field(default_factory=list)


class OutputConfig(BaseModel):
    remoteEvidenceRoot: str = "/var/lib/haifa-eval/evidence"
    localResultRoot: str
    retainRemoteEvidenceAfterPull: bool = True


class RunRequest(BaseModel):
    schemaVersion: int = 1
    runId: str
    target: TargetConfig
    source: SourceConfig
    evaluation: EvaluationConfig
    output: OutputConfig

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

        # Rule: Run entries must have unique IDs
        run_entry_ids = [run.id for run in self.evaluation.runs]
        if len(run_entry_ids) != len(set(run_entry_ids)):
            raise RequestValidationError(f"Duplicate run IDs in evaluation.runs: {run_entry_ids}")

        return self
