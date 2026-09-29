"""Tests for the SafeProgressTracker parsing the ladder runner output."""

from __future__ import annotations

from evalctl.harness.supervisor import SafeProgressTracker


def test_progress_tracker_parses_run_and_summary():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))

    tracker.handle_line("LADDER_RUN cases=23 repeat=1 total=23\n")
    tracker.handle_line("runs=23 passed=22 failed=1 incompleteBudget=0 wall=00:10:00\n")

    assert observed[0] == {"kind": "run", "cases": 23, "repeat": 1, "total": 23}
    assert observed[1]["kind"] == "summary"
    assert observed[1]["passed"] == 22


def test_progress_tracker_parses_case_result_and_progress():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))

    tracker.handle_line("  [ 1/23] L1-01 PASSED                12s checks 4/4  agent 11s exit=0 lines=3  changed 1: a.java\n")
    tracker.handle_line("  progress 1/23  PASSED 1 (100%)  FAILED 0  INCOMPLETE_BUDGET 0  elapsed 00:01:23\n")

    case_event = observed[0]
    assert case_event["kind"] == "case"
    assert case_event["caseId"] == "L1-01"
    assert case_event["status"] == "PASSED"
    assert case_event["attempt"] == 1

    progress_event = observed[1]
    assert progress_event["kind"] == "progress"
    assert progress_event["passed"] == 1
    assert progress_event["total"] == 23


def test_progress_tracker_parses_attempt_suffix():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))
    tracker.handle_line("  [ 4/24] H11-01.2 FAILED\n")
    assert observed[0]["caseId"] == "H11-01"
    assert observed[0]["attempt"] == 2
    assert observed[0]["status"] == "FAILED"


def test_progress_tracker_ignores_sensitive_or_noisy_lines():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))

    tracker.handle_line("API_KEY=secret_key_12345")
    tracker.handle_line("Prompt: Please write a sorting function in Python")
    tracker.handle_line("  [ 1/23] L1-01 working 45/600 lines=12 | thinking about the fix")
    tracker.handle_line("random stdout from maven")

    assert len(observed) == 0
    assert tracker.latest is None
