"""Integration tests: end-to-end workflow through the CLI with mocked LLM."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from sago.cli import app
from tests.conftest import SAMPLE_PLAN

runner = CliRunner()


UPDATED_XML = """\
<phases>
    <phase name="Phase 1: Foundation">
        <description>Set up project</description>

        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module</action>
            <verify>python -c "import config"</verify>
            <done>Config module exists</done>
        </task>

        <task id="1.2" depends_on="1.1">
            <name>Create main with CLI</name>
            <files>main.py</files>
            <action>Create main module with CLI</action>
            <verify>python -c "import main"</verify>
            <done>Main module with CLI exists</done>
        </task>

        <task id="1.3" depends_on="1.1,1.2">
            <name>Add logging</name>
            <files>logging_config.py</files>
            <action>Add structured logging</action>
            <verify>python -c "import logging_config"</verify>
            <done>Logging configured</done>
        </task>
    </phase>
</phases>"""


def test_init_creates_project(tmp_path: Path) -> None:
    """sago init should create all template files."""
    project_path = tmp_path / "test-project"
    result = runner.invoke(
        app, ["init", "test-project", "--path", str(project_path), "--yes"]
    )
    assert result.exit_code == 0
    assert "Project initialized" in result.output
    for filename in ["PROJECT.md", "REQUIREMENTS.md", "STATE.md", "CLAUDE.md", "IMPORTANT.md"]:
        assert (project_path / filename).exists(), f"{filename} not created"
    assert (project_path / ".planning").is_dir()


def test_plan_generates_plan(sago_project: Path) -> None:
    """sago plan should call the orchestrator and write PLAN.md."""
    from sago.agents.base import AgentResult, AgentStatus

    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan generated",
        metadata={"plan_path": str(sago_project / "PLAN.md")},
    )

    def fake_planner_execute(context: dict) -> AgentResult:
        (sago_project / "PLAN.md").write_text(SAMPLE_PLAN)
        return mock_result

    with (
        patch("sago.cli._check_llm_configured"),
        patch("sago.cli._check_placeholder_content"),
        patch(
            "sago.agents.planner.PlannerAgent.execute",
            new_callable=AsyncMock,
            side_effect=fake_planner_execute,
        ),
    ):
        result = runner.invoke(app, ["plan", "--path", str(sago_project), "--force"])

    assert result.exit_code == 0
    assert "Plan generated successfully" in result.output
    assert (sago_project / "PLAN.md").exists()


def test_status_after_plan(sago_project_with_plan: Path) -> None:
    """sago status should display progress when PLAN.md and STATE.md exist."""
    result = runner.invoke(app, ["status", "--path", str(sago_project_with_plan)])
    assert result.exit_code == 0
    assert "Project Status" in result.output
    assert "Task Progress" in result.output


def test_status_shows_completed_tasks(sago_project_with_plan: Path) -> None:
    """Status should reflect tasks marked complete in STATE.md."""
    result = runner.invoke(
        app, ["status", "--path", str(sago_project_with_plan), "--detailed"]
    )
    assert result.exit_code == 0
    assert "1" in result.output  # at least 1 completed
    assert "Create config" in result.output


def test_replan_one_shot(sago_project_with_plan: Path) -> None:
    """sago replan -f '...' -y should run non-interactively."""
    from sago.agents.base import AgentResult, AgentStatus

    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan updated",
        metadata={"plan_path": str(sago_project_with_plan / "PLAN.md")},
    )

    def fake_replan_execute(context: dict) -> AgentResult:
        # Write the updated plan
        updated_plan = f"# Updated Plan\n\n```xml\n{UPDATED_XML}\n```\n"
        (sago_project_with_plan / "PLAN.md").write_text(updated_plan)
        return mock_result

    mock_review_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Looks good",
        metadata={"phase_name": "Phase 1: Foundation"},
    )

    with (
        patch("sago.cli._check_llm_configured"),
        patch(
            "sago.agents.replanner.ReplannerAgent.execute",
            new_callable=AsyncMock,
            side_effect=fake_replan_execute,
        ),
        patch(
            "sago.agents.reviewer.ReviewerAgent.execute",
            new_callable=AsyncMock,
            return_value=mock_review_result,
        ),
    ):
        result = runner.invoke(
            app,
            [
                "replan",
                "--path", str(sago_project_with_plan),
                "--feedback", "add logging",
                "--yes",
            ],
        )

    assert result.exit_code == 0
    assert "Plan updated successfully" in result.output


def test_full_workflow_init_plan_status(tmp_path: Path) -> None:
    """Full workflow: init -> plan -> status."""
    from sago.agents.base import AgentResult, AgentStatus

    project_path = tmp_path / "full-test"

    # Step 1: init
    result = runner.invoke(
        app, ["init", "full-test", "--path", str(project_path), "--yes"]
    )
    assert result.exit_code == 0

    # Write real project content (not placeholders)
    (project_path / "PROJECT.md").write_text(
        "# Full Test\n\n## Project Vision\nA real test project.\n\n"
        "## Tech Stack & Constraints\n* Python\n\n"
        "## Core Architecture\nMonolith.\n"
    )
    (project_path / "REQUIREMENTS.md").write_text(
        "# Requirements\n\n## V1 Requirements (MVP)\n\n"
        '* [ ] **REQ-1:** Build the thing\n'
    )

    # Step 2: plan
    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan generated",
        metadata={"plan_path": str(project_path / "PLAN.md")},
    )

    def fake_planner(context: dict) -> AgentResult:
        (project_path / "PLAN.md").write_text(SAMPLE_PLAN)
        return mock_result

    with (
        patch("sago.cli._check_llm_configured"),
        patch("sago.cli._check_placeholder_content"),
        patch(
            "sago.agents.planner.PlannerAgent.execute",
            new_callable=AsyncMock,
            side_effect=fake_planner,
        ),
    ):
        result = runner.invoke(app, ["plan", "--path", str(project_path), "--force"])
    assert result.exit_code == 0

    # Step 3: status
    result = runner.invoke(app, ["status", "--path", str(project_path)])
    assert result.exit_code == 0
    assert "Project Status" in result.output
