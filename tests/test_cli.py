"""Unit tests for CLI commands using Typer's CliRunner."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from sago.cli import app

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
