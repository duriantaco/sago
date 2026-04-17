"""Executor-facing CLI JSON contract tests for the current builder contract."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from sago.cli import app
from sago.models.state import PhaseReview
from sago.state import StateManager

runner = CliRunner()


def _invoke_json(*args: str) -> dict[str, Any]:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _assert_keys(payload: dict[str, Any], expected: set[str]) -> None:
    assert set(payload) == expected


def _assert_agent_context_shape(agent_context: dict[str, Any]) -> None:
    _assert_keys(agent_context, {"present", "count", "files", "errors"})
    assert agent_context["present"] is True
    assert agent_context["count"] == len(agent_context["files"])
    assert agent_context["errors"] == []

    file_paths = {entry["path"] for entry in agent_context["files"]}
    assert {"IMPORTANT.md", "CLAUDE.md"} <= file_paths

    for entry in agent_context["files"]:
        _assert_keys(
            entry,
            {"path", "kind", "description", "line_count", "truncated"},
        )
        assert isinstance(entry["path"], str)
        assert isinstance(entry["kind"], str)
        assert isinstance(entry["description"], str)
        assert isinstance(entry["line_count"], int)
        assert isinstance(entry["truncated"], bool)


def _assert_resume_point_shape(resume_point: dict[str, Any]) -> None:
    _assert_keys(
        resume_point,
        {
            "last_completed",
            "next_task",
            "next_action",
            "failure_reason",
            "checkpoint",
        },
    )
    assert resume_point == {
        "last_completed": "1.1: Create config",
        "next_task": "1.2: Create main",
        "next_action": "Create main module",
        "failure_reason": "None",
        "checkpoint": "sago-checkpoint-1.1",
    }


def test_next_json_contract_task_state(sago_project_with_plan: Path) -> None:
    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")

    _assert_keys(
        payload,
        {
            "success",
            "state",
            "phase",
            "task",
            "dependency_status",
            "agent_context",
            "verify_warnings",
            "resume_point",
        },
    )
    assert payload["success"] is True
    assert payload["state"] == "task"
    assert payload["phase"] == "Phase 1: Foundation"

    _assert_keys(
        payload["task"],
        {"id", "name", "files", "action", "verify", "done", "phase_name", "depends_on"},
    )
    assert payload["task"] == {
        "id": "1.2",
        "name": "Create main",
        "files": ["main.py"],
        "action": "Create main module",
        "verify": 'python -c "import main"',
        "done": "Main module exists",
        "phase_name": "Phase 1: Foundation",
        "depends_on": ["1.1"],
    }

    assert payload["dependency_status"] == [{"task_id": "1.1", "status": "done"}]
    assert payload["verify_warnings"] == []
    _assert_agent_context_shape(payload["agent_context"])
    _assert_resume_point_shape(payload["resume_point"])


def test_next_json_contract_phase_review_required_after_tasks_complete(
    sago_project_with_plan: Path,
) -> None:
    checkpoint = runner.invoke(
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
    assert checkpoint.exit_code == 0, checkpoint.output

    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")

    _assert_keys(
        payload,
        {
            "success",
            "state",
            "message",
            "reason",
            "phase",
            "failed_tasks",
            "blocking_findings",
            "agent_context",
        },
    )
    assert payload["success"] is True
    assert payload["state"] == "blocked"
    assert payload["reason"] == "phase_review_required"
    assert payload["phase"] == "Phase 1: Foundation"
    assert payload["message"] == "Phase review required before continuing."
    assert payload["failed_tasks"] == 0
    assert payload["blocking_findings"] == []
    _assert_agent_context_shape(payload["agent_context"])


def test_next_json_contract_complete_state_after_review(sago_project_with_plan: Path) -> None:
    checkpoint = runner.invoke(
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
    assert checkpoint.exit_code == 0, checkpoint.output
    StateManager(sago_project_with_plan / "STATE.md").record_phase_review(
        PhaseReview(
            phase_name="Phase 1: Foundation",
            summary="Approved.",
            reviewer="judge",
        )
    )

    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")

    _assert_keys(payload, {"success", "state", "message", "agent_context"})
    assert payload["success"] is True
    assert payload["state"] == "complete"
    assert payload["message"] == "All tasks complete!"
    _assert_agent_context_shape(payload["agent_context"])


def test_next_json_contract_blocked_state(sago_project_with_plan: Path) -> None:
    checkpoint = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "failed",
            "--notes",
            "import error",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert checkpoint.exit_code == 0, checkpoint.output

    payload = _invoke_json("next", "--path", str(sago_project_with_plan), "--json")

    _assert_keys(payload, {"success", "state", "message", "failed_tasks", "agent_context"})
    assert payload["success"] is True
    assert payload["state"] == "blocked"
    assert payload["message"] == "No actionable tasks found."
    assert payload["failed_tasks"] == 1
    _assert_agent_context_shape(payload["agent_context"])


def test_status_json_contract_shape(sago_project_with_plan: Path) -> None:
    payload = _invoke_json("status", "--path", str(sago_project_with_plan), "--json")

    _assert_keys(
        payload,
        {
            "success",
            "project",
            "agent_context",
            "has_plan",
            "plan_error",
            "state",
            "task_summary",
            "evidence_summary",
            "memory_summary",
            "phases",
            "phase_gates",
            "recommendations",
            "blockers",
            "next_steps",
        },
    )
    assert payload["success"] is True
    assert payload["has_plan"] is True
    assert payload["plan_error"] is None
    assert payload["blockers"] == []

    _assert_keys(
        payload["project"],
        {"path", "name", "exists", "has_planning_dir", "template_files"},
    )
    assert payload["project"]["path"] == str(sago_project_with_plan)
    assert payload["project"]["name"] == sago_project_with_plan.name
    assert payload["project"]["exists"] is True
    assert payload["project"]["has_planning_dir"] is True
    assert payload["project"]["template_files"] == {
        "PROJECT.md": True,
        "REQUIREMENTS.md": True,
        "STATE.md": True,
        "IMPORTANT.md": True,
        "CLAUDE.md": True,
    }

    _assert_agent_context_shape(payload["agent_context"])

    _assert_keys(
        payload["state"],
        {
            "active_phase",
            "current_task",
            "task_states",
            "decisions",
            "blockers",
            "resume_point",
            "phase_reviews",
        },
    )
    assert payload["state"]["active_phase"] == "Phase 1: Foundation"
    assert payload["state"]["current_task"] == "1.2: Create main"
    assert payload["state"]["decisions"] == []
    assert payload["state"]["blockers"] == []
    assert payload["state"]["phase_reviews"] == {}

    task_states = payload["state"]["task_states"]
    assert len(task_states) == 2
    for task_state in task_states:
        _assert_keys(task_state, {"task_id", "status", "note"})
        assert task_state["note"] == ""
    assert {task_state["task_id"]: task_state["status"] for task_state in task_states} == {
        "1.1": "done",
        "1.2": "pending",
    }
    _assert_resume_point_shape(payload["state"]["resume_point"])

    assert payload["task_summary"] == {
        "completed": 1,
        "failed": 0,
        "pending": 1,
        "skipped": 0,
        "total": 2,
    }
    assert payload["evidence_summary"] == {
        "receipts": 0,
        "verified_done": 0,
        "missing_done": 1,
        "repeated_failures": 0,
    }
    assert payload["memory_summary"] == {
        "decision_count": 0,
        "blocker_count": 0,
        "reviewed_phase_count": 0,
        "decisions": [],
        "blockers": [],
        "reviewed_phases": [],
    }

    assert payload["phases"] == [
        {
            "name": "Phase 1: Foundation",
            "done": 1,
            "failed": 0,
            "skipped": 0,
            "pending": 1,
            "total": 2,
            "status": "partial",
        }
    ]
    assert payload["phase_gates"] == []

    assert payload["next_steps"] == [
        "Point your coding agent at this project",
        "Read repo-local agent instructions such as IMPORTANT.md, AGENTS.md, or CLAUDE.md",
        "sago status -d - Detailed task status",
    ]

    assert isinstance(payload["recommendations"], list)
    assert payload["recommendations"]
    for recommendation in payload["recommendations"]:
        _assert_keys(
            recommendation,
            {"type", "message", "task_id", "phase_name", "dismissible"},
        )
        assert isinstance(recommendation["type"], str)
        assert isinstance(recommendation["message"], str)
        assert isinstance(recommendation["dismissible"], bool)


def test_checkpoint_json_contract_shape(sago_project_with_plan: Path) -> None:
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

    _assert_keys(
        payload,
        {
            "success",
            "task_id",
            "task_name",
            "status",
            "notes",
            "next_task",
            "next_action",
            "decisions",
            "phase_name",
            "phase_completed",
            "phase_complete_name",
            "git_tag_created",
            "receipt",
            "evidence_summary",
        },
    )
    assert payload == {
        "success": True,
        "task_id": "1.1",
        "task_name": "Create config",
        "status": "done",
        "notes": "Config works",
        "next_task": "1.2: Create main",
        "next_action": "Implement main module",
        "decisions": ["Chose YAML over JSON", "Using pydantic"],
        "phase_name": "Phase 1: Foundation",
        "phase_completed": False,
        "phase_complete_name": "",
        "git_tag_created": False,
        "receipt": {
            "attached": False,
            "receipt_id": None,
            "path": None,
        },
        "evidence_summary": {
            "receipts": 0,
            "verified_done": 0,
            "missing_done": 1,
            "repeated_failures": 0,
        },
    }
