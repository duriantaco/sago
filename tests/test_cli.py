"""Unit tests for CLI commands using Typer's CliRunner."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

import sago.commands as commands_pkg
from sago.cli import app
from sago.commands import get_phase_status
from sago.commands.replan_cmd import _review_phases
from sago.models.plan import Phase, Task
from sago.models.state import TaskState, TaskStatus
from tests.conftest import SAMPLE_PLAN

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "sago" in result.output
    assert "version" in result.output


def test_init_with_yes_flag(tmp_path: Path) -> None:
    project_path = tmp_path / "my-project"
    result = runner.invoke(app, ["init", "my-project", "--path", str(project_path), "--yes"])
    assert result.exit_code == 0
    assert "Project initialized" in result.output
    assert (project_path / "PROJECT.md").exists()
    assert (project_path / "REQUIREMENTS.md").exists()
    assert (project_path / "STATE.md").exists()
    assert (project_path / "CLAUDE.md").exists()
    assert (project_path / ".planning").is_dir()


def test_init_with_prompt_no_llm(tmp_path: Path) -> None:
    """init --prompt should fail gracefully when no API key is configured."""
    project_path = tmp_path / "prompted"
    runner.invoke(
        app,
        ["init", "prompted", "--path", str(project_path), "--yes", "--prompt", "a todo app"],
    )
    # Should still create the project (with placeholder files) even if prompt generation fails
    assert (project_path / "PROJECT.md").exists()


def test_init_no_name_no_tty(tmp_path: Path) -> None:
    """init without a name and non-interactive should fail."""
    result = runner.invoke(app, ["init", "--path", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    assert "required" in result.output.lower()


def test_plan_on_non_sago_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["plan", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Not a sago project" in result.output


def test_plan_missing_files(sago_project: Path) -> None:
    """plan should fail if PROJECT.md or REQUIREMENTS.md is missing."""
    (sago_project / "REQUIREMENTS.md").unlink()
    with patch("sago.commands.plan_cmd.check_llm_configured"):
        result = runner.invoke(app, ["plan", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "Missing required files" in result.output


def test_plan_missing_llm_key_does_not_print_error_number(sago_project: Path) -> None:
    result = runner.invoke(app, ["plan", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "Missing API Key" in result.output
    assert "Error: 1" not in result.output


def test_plan_yes_skips_placeholder_prompt(tmp_path: Path) -> None:
    from sago.agents.base import AgentResult, AgentStatus

    project_path = tmp_path / "placeholder-project"
    init_result = runner.invoke(app, ["init", "placeholder-project", "--path", str(project_path), "--yes"])
    assert init_result.exit_code == 0

    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan generated",
        metadata={"plan_path": str(project_path / "PLAN.md")},
    )

    async def fake_planner_execute(_context: dict) -> AgentResult:
        (project_path / "PLAN.md").write_text(SAMPLE_PLAN, encoding="utf-8")
        return mock_result

    with (
        patch("sago.commands.plan_cmd.check_llm_configured"),
        patch(
            "sago.agents.planner.PlannerAgent.execute",
            new_callable=AsyncMock,
            side_effect=fake_planner_execute,
        ),
    ):
        result = runner.invoke(app, ["plan", "--path", str(project_path), "--force", "--yes"])

    assert result.exit_code == 0
    assert "Continue anyway?" not in result.output
    assert (project_path / "PLAN.md").exists()


def test_status_on_valid_project(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["status", "--path", str(sago_project_with_plan)])
    assert result.exit_code == 0
    assert "Project Status" in result.output


def test_status_json(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["status", "--path", str(sago_project_with_plan), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["agent_context"]["present"] is True
    assert {entry["path"] for entry in payload["agent_context"]["files"]} >= {
        "IMPORTANT.md",
        "CLAUDE.md",
    }
    assert payload["has_plan"] is True
    assert payload["task_summary"]["completed"] >= 1
    assert payload["phases"]


def test_status_on_non_sago_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["status", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Not a sago project" in result.output


def test_status_detailed(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["status", "--path", str(sago_project_with_plan), "--detailed"])
    assert result.exit_code == 0
    assert "Task Progress" in result.output


def test_replan_on_non_sago_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["replan", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Not a sago project" in result.output


def test_replan_no_plan(sago_project: Path) -> None:
    """replan should fail if there's no PLAN.md."""
    with patch("sago.commands.replan_cmd.check_llm_configured"):
        result = runner.invoke(app, ["replan", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "No PLAN.md found" in result.output


def test_checkpoint_done(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "done",
            "--notes",
            "Config works",
            "--next",
            "1.2: Create main",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0
    assert "1.1" in result.output
    state = (sago_project_with_plan / "STATE.md").read_text()
    assert "[✓] 1.1: Create config — Config works" in state


def test_checkpoint_failed(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "failed",
            "--notes",
            "import error",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0
    state = (sago_project_with_plan / "STATE.md").read_text()
    assert "[✗] 1.2: Create main — import error" in state


def test_checkpoint_json(sago_project_with_plan: Path) -> None:
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
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["task_id"] == "1.2"
    assert payload["status"] == "done"


def test_checkpoint_with_decisions(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "done",
            "-d",
            "Chose YAML over JSON",
            "-d",
            "Using pydantic",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0
    state = (sago_project_with_plan / "STATE.md").read_text()
    assert "Chose YAML over JSON" in state
    assert "Using pydantic" in state


def test_checkpoint_invalid_task(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        ["checkpoint", "99.99", "--path", str(sago_project_with_plan), "--no-git-tag"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_checkpoint_invalid_status(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "invalid",
            "--path",
            str(sago_project_with_plan),
        ],
    )
    assert result.exit_code == 1


def test_checkpoint_no_plan(sago_project: Path) -> None:
    result = runner.invoke(
        app,
        ["checkpoint", "1.1", "--path", str(sago_project), "--no-git-tag"],
    )
    assert result.exit_code == 1
    assert "No PLAN.md found" in result.output


def test_checkpoint_auto_phase_complete(sago_project_with_plan: Path) -> None:
    """Completing all tasks in a phase shows phase complete message."""
    # Mark both tasks in Phase 1 as done
    runner.invoke(
        app,
        ["checkpoint", "1.1", "--path", str(sago_project_with_plan), "--no-git-tag"],
    )
    result = runner.invoke(
        app,
        ["checkpoint", "1.2", "--path", str(sago_project_with_plan), "--no-git-tag"],
    )
    assert result.exit_code == 0
    assert "Phase complete" in result.output
    assert "sago replan" in result.output
    state = (sago_project_with_plan / "STATE.md").read_text()
    assert "## Phase Complete:" in state


def test_next_task(sago_project_with_plan: Path) -> None:
    """next shows the first pending task."""
    result = runner.invoke(app, ["next", "--path", str(sago_project_with_plan)])
    assert result.exit_code == 0
    # Task 1.1 is already done (from SAMPLE_STATE), so next should be 1.2
    assert "1.2" in result.output
    assert "Create main" in result.output


def test_next_task_json(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["next", "--path", str(sago_project_with_plan), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["state"] == "task"
    assert payload["agent_context"]["present"] is True
    assert payload["task"]["id"] == "1.2"


def test_next_task_all_done(sago_project_with_plan: Path) -> None:
    """next shows completion message when all tasks are done."""
    # Mark all tasks done
    for tid in ("1.1", "1.2"):
        runner.invoke(
            app,
            ["checkpoint", tid, "--path", str(sago_project_with_plan), "--no-git-tag"],
        )
    # 1.1 was already done in SAMPLE_STATE, but we need to handle the 2-task plan
    # The sample plan only has tasks 1.1 and 1.2
    result = runner.invoke(app, ["next", "--path", str(sago_project_with_plan)])
    assert result.exit_code == 0
    assert "complete" in result.output.lower()


def test_next_task_all_done_or_skipped(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint",
            "1.2",
            "--status",
            "skipped",
            "--path",
            str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0

    next_result = runner.invoke(app, ["next", "--path", str(sago_project_with_plan), "--json"])
    assert next_result.exit_code == 0
    payload = json.loads(next_result.output)
    assert payload["state"] == "complete"


def test_next_task_no_plan(sago_project: Path) -> None:
    result = runner.invoke(app, ["next", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "No PLAN.md found" in result.output


def test_doctor_json(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["doctor", "--path", str(sago_project_with_plan), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["summary"]["fail"] == 0
    check_names = {check["name"] for check in payload["checks"]}
    assert {
        "project_path",
        "project_files",
        "agent_context",
        "dashboard_asset",
        "plan",
        "state",
    } <= check_names


def test_doctor_missing_path_does_not_create_planning_dir(
    tmp_path: Path, monkeypatch
) -> None:
    missing_project = tmp_path / "missing-project"
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor", "--path", str(missing_project), "--json"])

    assert result.exit_code == 1
    assert not (tmp_path / ".planning").exists()


def test_load_config_project_path_creates_project_planning_dir(
    tmp_path: Path, monkeypatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    project_path = tmp_path / "project"
    project_path.mkdir()

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(commands_pkg, "_config", None)

    cfg = commands_pkg.load_config(project_path)

    assert cfg.planning_dir == project_path / ".planning"
    assert (project_path / ".planning").exists()
    assert not (cwd / ".planning").exists()


def test_get_phase_status_counts_skipped_without_pending() -> None:
    phase = Phase(
        name="Phase 1",
        description="",
        tasks=[
            Task(
                id="1.1",
                name="Done task",
                files=["done.py"],
                action="x",
                verify="python -c 'print(1)'",
                done="done",
                phase_name="Phase 1",
            ),
            Task(
                id="1.2",
                name="Skipped task",
                files=["skip.py"],
                action="x",
                verify="python -c 'print(1)'",
                done="done",
                phase_name="Phase 1",
            ),
        ],
    )
    statuses = get_phase_status(
        [phase],
        [
            TaskState(task_id="1.1", status=TaskStatus.DONE),
            TaskState(task_id="1.2", status=TaskStatus.SKIPPED),
        ],
    )

    assert statuses[0]["skipped"] == 1
    assert statuses[0]["pending"] == 0
    assert statuses[0]["status"] == "complete"


def test_replan_only_reviews_completed_phases(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    state_file.write_text("", encoding="utf-8")
    phases = [
        Phase(
            name="Phase 1",
            description="",
            tasks=[
                Task(
                    id="1.1",
                    name="Task",
                    files=["task.py"],
                    action="x",
                    verify="python -c 'print(1)'",
                    done="done",
                    phase_name="Phase 1",
                )
            ],
        )
    ]

    class FakeOrchestrator:
        async def run_review(
            self, project_path: Path, phase: Phase, review_prompt: str
        ) -> SimpleNamespace:
            return SimpleNamespace(success=True, output=f"reviewed {phase.name}", error=None)

    outputs = _review_phases(
        tmp_path,
        phases,
        [
            {
                "name": "Phase 1",
                "done": 0,
                "failed": 1,
                "skipped": 0,
                "pending": 0,
                "total": 1,
                "status": "partial",
            }
        ],
        state_file,
        "review prompt",
        FakeOrchestrator(),
    )

    assert outputs == []
    assert state_file.read_text(encoding="utf-8") == ""
