"""Tests for Plan Set approval verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evalctl.core.errors import PlanApprovalError
from evalctl.harness.approval import verify_and_record_approval


def test_approval_digest_match_succeeds(tmp_path: Path):
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir(parents=True)

    plan_set = {
        "schemaVersion": 1,
        "runId": "test-run",
        "planSetSha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        "plans": [{"runEntryId": "cp-smoke", "budget": "5"}],
    }
    (plans_dir / "plan-set.json").write_text(json.dumps(plan_set), encoding="utf-8")

    record = verify_and_record_approval(
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
        plans_dir,
        operator_id="test-operator",
    )
    assert record["operator"] == "test-operator"
    assert (plans_dir / "approval.json").is_file()


def test_approval_digest_mismatch_fails_closed(tmp_path: Path):
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir(parents=True)

    plan_set = {
        "schemaVersion": 1,
        "runId": "test-run",
        "planSetSha256": "1111111111111111111111111111111111111111111111111111111111111111",
        "plans": [],
    }
    (plans_dir / "plan-set.json").write_text(json.dumps(plan_set), encoding="utf-8")

    with pytest.raises(PlanApprovalError, match="Approval Digest Mismatch"):
        verify_and_record_approval(
            "2222222222222222222222222222222222222222222222222222222222222222",
            plans_dir,
            operator_id="test-operator",
        )
