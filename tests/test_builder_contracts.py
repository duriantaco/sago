"""Fixture-backed builder contract tests for Codex-oriented JSON payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from sago.cli import app
from sago.models.state import PhaseReview
from sago.state import StateManager

runner = CliRunner()
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "builder_contracts"


def _invoke_json(*args: str) -> dict[str, Any]:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _write_receipt(project_path: Path, *, task_id: str, status: str, exit_code: int) -> Path:
    receipt = {
        "receipt_id": f"receipt-{task_id}-fixture",
        "task_id": task_id,
        "status": status,
        "verify_command": "pytest -q",
        "exit_code": exit_code,
        "stdout": "ok" if exit_code == 0 else "",
        "stderr": "" if exit_code == 0 else "AssertionError: failure",
        "duration_ms": 42,
        "files_changed": [f"{task_id}.py"],
        "recorded_at": "2026-04-17T12:00:00Z",
        "builder": "codex",
        "git_head": "abc1234",
    }
    path = project_path / f"{receipt['receipt_id']}.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_builder_contract_next_task_fixture(sago_project_with_plan: Path) -> None:
    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")
    fixture = _load_fixture("next_task.json")

    assert set(payload) == set(fixture["keys"])
    assert payload["state"] == fixture["state"]
    assert payload["phase"] == fixture["phase"]
    assert payload["task"] == fixture["task"]
    assert payload["dependency_status"] == fixture["dependency_status"]
    assert payload["verify_warnings"] == fixture["verify_warnings"]


def test_builder_contract_next_phase_gate_fixture(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "done",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0, result.output

    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")
    fixture = _load_fixture("next_phase_review_required.json")

    assert set(payload) == set(fixture["keys"])
    for key, value in fixture["exact"].items():
        assert payload[key] == value


def test_builder_contract_status_fixture(sago_project_with_plan: Path) -> None:
    payload = _invoke_json("status", "--path", str(sago_project_with_plan), "--json")
    fixture = _load_fixture("status_base.json")

    assert set(payload) == set(fixture["keys"])
    assert set(payload["project"]) == set(fixture["project_keys"])
    assert set(payload["state"]) == set(fixture["state_keys"])
    assert payload["task_summary"] == fixture["task_summary"]
    assert payload["evidence_summary"] == fixture["evidence_summary"]
    assert payload["memory_summary"] == fixture["memory_summary"]
    assert payload["phase_gates"] == fixture["phase_gates"]


def test_builder_contract_status_reviewed_phase_fixture(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "done",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0, result.output
    StateManager(sago_project_with_plan / "STATE.md").record_phase_review(
        PhaseReview(
            phase_name="Phase 1: Foundation",
            summary="Approved after review.",
            reviewer="judge",
        )
    )

    payload = _invoke_json("status", "--path", str(sago_project_with_plan), "--json")
    fixture = _load_fixture("status_reviewed_phase.json")

    phase_gate = payload["phase_gates"][0]
    assert phase_gate["phase_name"] == fixture["phase_gates"][0]["phase_name"]
    assert phase_gate["status"] == fixture["phase_gates"][0]["status"]
    assert phase_gate["blocking_findings"] == fixture["phase_gates"][0]["blocking_findings"]
    assert phase_gate["summary"] == fixture["phase_gates"][0]["summary"]
    assert isinstance(phase_gate["reviewed_at"], str) and phase_gate["reviewed_at"]

    phase_review = payload["state"]["phase_reviews"]["Phase 1: Foundation"]
    expected_review = fixture["phase_reviews"]["Phase 1: Foundation"]
    assert phase_review["phase_name"] == expected_review["phase_name"]
    assert phase_review["summary"] == expected_review["summary"]
    assert phase_review["gate_status"] == expected_review["gate_status"]
    assert phase_review["reviewer"] == expected_review["reviewer"]
    assert phase_review["finding_count"] == expected_review["finding_count"]
    assert phase_review["findings"] == expected_review["findings"]
    assert isinstance(phase_review["reviewed_at"], str) and phase_review["reviewed_at"]


def test_builder_contract_checkpoint_fixture(sago_project_with_plan: Path) -> None:
    payload = _invoke_json(
        "checkpoint",
        "1.1",
        "--status",
        "done",
        "--notes",
        "Config works",
        "--next",
        "1.2: Create main",
        "--next-action",
        "Implement main module",
        "--decision",
        "Chose YAML over JSON",
        "--decision",
        "Using pydantic",
        "--path",
        str(sago_project_with_plan),
        "--no-git-tag",
        "--json",
    )
    fixture = _load_fixture("checkpoint_done.json")

    assert set(payload) == set(fixture["keys"])
    assert payload == fixture["payload"]


def test_builder_contract_checkpoint_receipt_fixture(sago_project_with_plan: Path) -> None:
    receipt_path = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="done",
        exit_code=0,
    )
    payload = _invoke_json(
        "checkpoint",
        "1.2",
        "--status",
        "done",
        "--receipt-file",
        str(receipt_path),
        "--path",
        str(sago_project_with_plan),
        "--no-git-tag",
        "--json",
    )
    fixture = _load_fixture("checkpoint_with_receipt.json")

    assert payload["receipt"] == fixture["receipt"]
