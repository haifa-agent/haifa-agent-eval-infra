"""Append-only lifecycle event journal manager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class LifecycleStage(StrEnum):
    REQUEST_VALIDATED = "REQUEST_VALIDATED"
    HOST_TRUSTED = "HOST_TRUSTED"
    HOST_PREFLIGHTED = "HOST_PREFLIGHTED"
    BOOTSTRAPPED = "BOOTSTRAPPED"
    SOURCE_PINNED = "SOURCE_PINNED"
    MODEL_PROFILE_VERIFIED = "MODEL_PROFILE_VERIFIED"
    PLAN_CREATED = "PLAN_CREATED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RUNNING = "RUNNING"
    EVIDENCE_READY = "EVIDENCE_READY"
    EVIDENCE_PULLED = "EVIDENCE_PULLED"
    REPORT_READY = "REPORT_READY"
    COMPLETE = "COMPLETE"

    # Terminal failure states
    FAILED_REQUEST_VALIDATION = "FAILED_REQUEST_VALIDATION"
    FAILED_HOST_TRUST = "FAILED_HOST_TRUST"
    FAILED_HOST_PREFLIGHT = "FAILED_HOST_PREFLIGHT"
    FAILED_BOOTSTRAP = "FAILED_BOOTSTRAP"
    FAILED_SOURCE_PIN = "FAILED_SOURCE_PIN"
    FAILED_MODEL_PROFILE = "FAILED_MODEL_PROFILE"
    FAILED_PLAN = "FAILED_PLAN"
    FAILED_RUN = "FAILED_RUN"
    FAILED_EVIDENCE = "FAILED_EVIDENCE"
    FAILED_REPORT = "FAILED_REPORT"
    CANCELLED = "CANCELLED"


class LifecycleStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    IN_PROGRESS = "IN_PROGRESS"
    CANCELLED = "CANCELLED"


class LifecycleManager:
    """Manages append-only lifecycle.jsonl records."""

    def __init__(self, run_id: str, local_control_dir: Path) -> None:
        self.run_id = run_id
        self.control_dir = local_control_dir
        self.journal_path = local_control_dir / "lifecycle.jsonl"
        self.control_dir.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        stage: LifecycleStage,
        status: LifecycleStatus = LifecycleStatus.SUCCESS,
        *,
        exit_code: int | None = None,
        reason_code: str | None = None,
        artifacts: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "runId": self.run_id,
            "stage": stage.value,
            "status": status.value,
            "exitCode": exit_code,
            "reasonCode": reason_code,
            "artifacts": artifacts or {},
            "extra": extra or {},
        }
        with self.journal_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def read_events(self) -> list[dict[str, Any]]:
        if not self.journal_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        with self.journal_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def latest_stage(self) -> str | None:
        events = self.read_events()
        if not events:
            return None
        return events[-1].get("stage")
