import pytest

from evalctl.harness.supervisor import safe_evals_line


@pytest.mark.parametrize(
    "line",
    [
        "[supervisor-harbor] Syncing frozen evals repository...",
        "[driver] admission: ADMITTED",
        "[driver] run complete",
        "Running as unit: haifa-eval-x-evals.service; invocation ID: y",
        "Finished with result: exit-code",
    ],
)
def test_safe_evals_line_accepts_control_lines(line: str):
    assert safe_evals_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        '{"ZAI_API_KEY": "secret"}',
        "Traceback (most recent call last):",
        "raw model output line",
        "",
    ],
)
def test_safe_evals_line_rejects_other_output(line: str):
    assert safe_evals_line(line) is False
