"""Phase 2 receipt and execution-history coverage for checkpoint flows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from sago.cli import app
from sago.core.parser import MarkdownParser
from sago.models.execution import ExecutionHistory, FailureCategory
from sago.models.plan import Plan
from sago.models.state import ProjectState
from sago.recommendations import RecommendationEngine, RecommendationType
from sago.state import StateManager

runner = CliRunner()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_dir(project_path: Path) -> Path:
    return project_path / ".planning" / "runtime"


def _write_receipt(
    project_path: Path,
    *,
    task_id: str,
    status: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    recorded_at: str = "2026-04-16T10:15:00Z",
    suffix: str = "a",
) -> Path:
    timestamp = recorded_at.replace("-", "").replace(":", "")
    receipt = {
        "receipt_id": f"receipt-{task_id}-{timestamp}-{suffix}",
        "task_id": task_id,
        "status": status,
        "verify_command": "pytest tests/test_main.py -q",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": 1432,
        "files_changed": ["main.py", "tests/test_main.py"],
        "recorded_at": recorded_at,
        "builder": "codex",
        "git_head": "abc1234",
    }
    receipt_path = project_path / f"{receipt['receipt_id']}.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return receipt_path


def _load_plan_and_state(project_path: Path) -> tuple[Plan, ProjectState]:
    phases = MarkdownParser().parse_xml_tasks((project_path / "PLAN.md").read_text(encoding="utf-8"))
    state = StateManager(project_path / "STATE.md").get_project_state(phases)
    return Plan(phases=phases), state


def test_checkpoint_receipt_file_is_persisted_to_runtime_and_history(
    sago_project_with_plan: Path,
) -> None:
    receipt_path = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="failed",
        exit_code=1,
        stderr="ModuleNotFoundError: No module named 'config'",
    )

    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "failed",
            "--notes",
            "config import failed",
            "--receipt-file",
            str(receipt_path),
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )

    assert result.exit_code == 0, result.output

    receipts_dir = _runtime_dir(sago_project_with_plan) / "receipts"
    receipt_files = list(receipts_dir.glob("*.json"))
    assert len(receipt_files) == 1

    stored_receipt = _read_json(receipt_files[0])
    assert stored_receipt["task_id"] == "1.2"
    assert stored_receipt["status"] == "failed"
    assert stored_receipt["exit_code"] == 1
    assert stored_receipt["stderr"] == "ModuleNotFoundError: No module named 'config'"

    history_path = _runtime_dir(sago_project_with_plan) / "execution_history.json"
    assert history_path.exists()

    history = ExecutionHistory.from_json(history_path.read_text(encoding="utf-8"))
    assert len(history.records) == 1
    record = history.records[0]
    assert record.task_id == "1.2"
    assert record.verifier_result is not None
    assert record.verifier_result.exit_code == 1
    assert record.verifier_result.failure_category == FailureCategory.IMPORT_ERROR


def test_checkpoint_json_surfaces_receipt_metadata_and_evidence_summary(
    sago_project_with_plan: Path,
) -> None:
    receipt_path = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="done",
        exit_code=0,
        stdout="2 passed",
        recorded_at="2026-04-16T10:20:00Z",
        suffix="json",
    )

    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "done",
            "--notes",
            "verification passed",
            "--receipt-file",
            str(receipt_path),
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["receipt"] == {
        "attached": True,
        "receipt_id": "receipt-1.2-20260416T102000Z-json",
        "path": ".planning/runtime/receipts/receipt-1.2-20260416T102000Z-json.json",
    }
    assert payload["evidence_summary"] == {
        "receipts": 1,
        "verified_done": 1,
        "missing_done": 1,
        "repeated_failures": 0,
    }


def test_checkpoint_rejects_done_receipt_with_nonzero_exit_code(
    sago_project_with_plan: Path,
) -> None:
    receipt_path = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="done",
        exit_code=1,
        stderr="AssertionError: test failed",
        recorded_at="2026-04-16T10:21:00Z",
        suffix="invalid",
    )

    result = runner.invoke(
        app,
        [
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
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert "exit_code 0" in payload["error"]


def test_persisted_failed_receipts_drive_repeated_failure_recommendations(
    sago_project_with_plan: Path,
) -> None:
    first_receipt = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="failed",
        exit_code=1,
        stderr="ModuleNotFoundError: No module named 'config'",
        recorded_at="2026-04-16T10:15:00Z",
        suffix="first",
    )
    second_receipt = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="failed",
        exit_code=1,
        stderr="ModuleNotFoundError: No module named 'config'",
        recorded_at="2026-04-16T10:16:00Z",
        suffix="second",
    )

    first = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "failed",
            "--notes",
            "first attempt failed",
            "--receipt-file",
            str(first_receipt),
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    second = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "failed",
            "--notes",
            "second attempt failed",
            "--receipt-file",
            str(second_receipt),
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    history_path = _runtime_dir(sago_project_with_plan) / "execution_history.json"
    history = ExecutionHistory.from_json(history_path.read_text(encoding="utf-8"))
    plan, state = _load_plan_and_state(sago_project_with_plan)

    recommendations = RecommendationEngine().evaluate(plan=plan, state=state, execution_history=history)
    repeated_failures = [
        rec for rec in recommendations if rec.type == RecommendationType.WARN_REPEATED_FAILURE
    ]

    assert len(repeated_failures) == 1
    assert repeated_failures[0].task_id == "1.2"
    assert "failed multiple times" in repeated_failures[0].message.lower()


def test_status_json_recommends_missing_evidence_for_done_task_without_receipt(
    sago_project_with_plan: Path,
) -> None:
    checkpoint = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "done",
            "--notes",
            "main module works",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert checkpoint.exit_code == 0, checkpoint.output

    status = runner.invoke(app, ["status", "--path", str(sago_project_with_plan), "--json"])
    assert status.exit_code == 0, status.output

    payload = json.loads(status.output)
    assert any(
        recommendation.get("task_id") == "1.2"
        and (
            "receipt" in recommendation["message"].lower()
            or "evidence" in recommendation["message"].lower()
        )
        for recommendation in payload["recommendations"]
    )


def test_successful_receipt_is_stored_with_non_failure_classification(
    sago_project_with_plan: Path,
) -> None:
    receipt_path = _write_receipt(
        sago_project_with_plan,
        task_id="1.2",
        status="done",
        exit_code=0,
        stdout="2 passed in 0.42s",
        recorded_at="2026-04-16T10:17:00Z",
        suffix="success",
    )

    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "done",
            "--notes",
            "tests passed",
            "--receipt-file",
            str(receipt_path),
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )

    assert result.exit_code == 0, result.output

    receipts_dir = _runtime_dir(sago_project_with_plan) / "receipts"
    stored_receipt = _read_json(next(receipts_dir.glob("*.json")))
    assert stored_receipt["status"] == "done"
    assert stored_receipt["stdout"] == "2 passed in 0.42s"

    history = ExecutionHistory.from_json(
        (_runtime_dir(sago_project_with_plan) / "execution_history.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(history.records) == 1

    record = history.records[0]
    assert record.task_id == "1.2"
    assert record.verifier_result is not None
    assert record.verifier_result.exit_code == 0
    assert record.verifier_result.failure_category in (None, FailureCategory.UNKNOWN)
    assert record.files_changed == ["main.py", "tests/test_main.py"]
