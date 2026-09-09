"""Tests for SafeProgressTracker progress parsing and filtering."""

from __future__ import annotations

from evalctl.harness.supervisor import SafeProgressTracker


def test_progress_tracker_extracts_safe_fields():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))

    line = "[delivery-progress] phase=autonomous-delivery evaluated=6/26 passed=5/26 currentCase=AD-06 currentRepetition=1\n"
    tracker.handle_line(line)

    assert len(observed) == 1
    assert observed[0]["phase"] == "autonomous-delivery"
    assert observed[0]["evaluated"] == "6/26"
    assert observed[0]["passed"] == "5/26"
    assert observed[0]["currentCase"] == "AD-06"
    assert observed[0]["currentRepetition"] == "1"


def test_progress_tracker_ignores_sensitive_or_noisy_lines():
    observed = []
    tracker = SafeProgressTracker(on_progress=lambda p: observed.append(p))

    # Prompts, secret environment variables, stack traces should be ignored
    tracker.handle_line("API_KEY=secret_key_12345")
    tracker.handle_line("Prompt: Please write a sorting function in Python")
    tracker.handle_line("Thinking: The user wants me to fix the bug...")
    tracker.handle_line("random stdout from maven")

    assert len(observed) == 0
    assert tracker.latest is None
