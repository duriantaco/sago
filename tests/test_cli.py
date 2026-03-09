"""Unit tests for CLI commands using Typer's CliRunner."""

from pathlib import Path
from unittest.mock import patch

from click.exceptions import Exit
import pytest
from typer.testing import CliRunner

import sago.cli as cli
from sago.cli import app
from sago.core.config import Config

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
    with patch("sago.cli._check_llm_configured"):
        result = runner.invoke(app, ["plan", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "Missing required files" in result.output


def test_status_on_valid_project(sago_project_with_plan: Path) -> None:
    result = runner.invoke(app, ["status", "--path", str(sago_project_with_plan)])
    assert result.exit_code == 0
    assert "Project Status" in result.output


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
    with patch("sago.cli._check_llm_configured"):
        result = runner.invoke(app, ["replan", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "No PLAN.md found" in result.output


def test_checkpoint_done(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint", "1.1",
            "--status", "done",
            "--notes", "Config works",
            "--next", "1.2: Create main",
            "--path", str(sago_project_with_plan),
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
            "checkpoint", "1.2",
            "--status", "failed",
            "--notes", "import error",
            "--path", str(sago_project_with_plan),
            "--no-git-tag",
        ],
    )
    assert result.exit_code == 0
    state = (sago_project_with_plan / "STATE.md").read_text()
    assert "[✗] 1.2: Create main — import error" in state


def test_checkpoint_with_decisions(sago_project_with_plan: Path) -> None:
    result = runner.invoke(
        app,
        [
            "checkpoint", "1.1",
            "--status", "done",
            "-d", "Chose YAML over JSON",
            "-d", "Using pydantic",
            "--path", str(sago_project_with_plan),
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
            "checkpoint", "1.1",
            "--status", "invalid",
            "--path", str(sago_project_with_plan),
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


def test_next_task_no_plan(sago_project: Path) -> None:
    result = runner.invoke(app, ["next", "--path", str(sago_project)])
    assert result.exit_code == 1
    assert "No PLAN.md found" in result.output
