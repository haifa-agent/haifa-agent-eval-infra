"""Tests for LifecycleManager event recording and persistence."""

from __future__ import annotations

from pathlib import Path

from evalctl.core.lifecycle import LifecycleManager, LifecycleStage, LifecycleStatus


def test_lifecycle_record_and_read(tmp_path: Path):
    control_dir = tmp_path / "control"
    manager = LifecycleManager("test-run-123", control_dir)

    manager.record(LifecycleStage.REQUEST_VALIDATED)
    manager.record(LifecycleStage.HOST_TRUSTED, extra={"fingerprint": "SHA256:abc"})
    manager.record(LifecycleStage.RUNNING, status=LifecycleStatus.IN_PROGRESS)

    events = manager.read_events()
    assert len(events) == 3
    assert events[0]["stage"] == "REQUEST_VALIDATED"
    assert events[1]["extra"]["fingerprint"] == "SHA256:abc"
    assert events[2]["status"] == "IN_PROGRESS"
    assert manager.latest_stage() == "RUNNING"
