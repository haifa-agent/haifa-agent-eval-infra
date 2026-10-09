"""Integration tests for the kind: haifa-evals-harbor workflow (mocked evidence)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from evalctl.config.loader import load_run_request
from evalctl.evidence.verifier import verify_evals_summary
from evalctl.harness.supervisor import build_evals_spec


def _write_harbor_request(sample_request_path: Path, tmp_path: Path) -> Path:
    raw = yaml.safe_load(sample_request_path.read_text(encoding="utf-8"))
    raw["runId"] = "tb2-smoke-001"
    raw["source"]["product"] = {
        "url": "git@github.com:haifa-agent/haifa-agent-evals.git",
        "commit": "0123456789abcdef0123456789abcdef01234567",
    }
    raw["evaluation"] = {
        "kind": "haifa-evals-harbor",
        "providerId": "zhipu",
        "modelId": "glm-5.3-flash",
        "evalId": "coding-terminal-bench2-glm53-smoke-v1",
        "apiBaseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "allowRealProvider": True,
        "requiredSecretEnvironmentNames": ["BIGMODEL_API_KEY"],
    }
    request_path = tmp_path / "harbor_request.yaml"
    request_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return request_path


def test_harbor_request_round_trip(sample_request_path: Path, tmp_path: Path):
    request_path = _write_harbor_request(sample_request_path, tmp_path)
    req, _, _ = load_run_request(
        request_path, validate_local_keys=False, validate_local_result_root=False
    )

    assert req.evaluation.kind == "haifa-evals-harbor"
    assert req.evaluation.evalId == "coding-terminal-bench2-glm53-smoke-v1"


def test_evals_spec_uses_frozen_evals_worktree(sample_request_path: Path, tmp_path: Path):
    request_path = _write_harbor_request(sample_request_path, tmp_path)
    req, _, _ = load_run_request(
        request_path, validate_local_keys=False, validate_local_result_root=False
    )

    spec = build_evals_spec(req, "/run/haifa-eval/tb2-smoke-001/secrets.env")

    assert spec["worktree"].endswith("/haifa-agent-evals")
    assert spec["evalId"] == req.evaluation.evalId
    assert spec["secretsPath"] == "/run/haifa-eval/tb2-smoke-001/secrets.env"
    assert spec["outputDir"] == f"{req.output.remoteEvidenceRoot}/{req.runId}"


def test_evals_summary_requires_companion_artifacts(tmp_path: Path):
    (tmp_path / "evals-summary.json").write_text(
        json.dumps({"evalId": "smoke", "attemptCount": 1}), encoding="utf-8"
    )
    (tmp_path / "results.csv").write_text(
        "task_id,reward\nterminal-bench/overfull-hbox,1.0\n", encoding="utf-8"
    )
    (tmp_path / "preflight.json").write_text(
        json.dumps({"status": "READY"}), encoding="utf-8"
    )

    verify_evals_summary(tmp_path)
