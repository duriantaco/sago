from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sago.agents.base import AgentResult, AgentStatus
from sago.agents.orchestrator import Orchestrator, WorkflowResult
from sago.core.config import Config


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    return Config()


@pytest.fixture
def sample_plan_content() -> str:
    return """# PLAN.md

```xml
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

        <task id="1.2">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main module</action>
            <verify>python -c "import main"</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>
```
"""


@pytest.fixture
def orchestrator(mock_config: Config) -> Orchestrator:
    return Orchestrator(config=mock_config)


def test_orchestrator_initialization(orchestrator: Orchestrator):
    assert orchestrator is not None
    assert orchestrator.planner is not None
    assert orchestrator.parser is not None
    assert orchestrator.project_manager is not None


def test_workflow_result_to_dict():
    """Test WorkflowResult serialization."""
    result = WorkflowResult(
        success=True,
        total_tasks=5,
        completed_tasks=5,
        failed_tasks=0,
        skipped_tasks=0,
        total_duration=10.5,
    )

    data = result.to_dict()

    assert data["success"] is True
    assert data["total_tasks"] == 5
    assert data["completed_tasks"] == 5
    assert data["failed_tasks"] == 0
    assert data["total_duration"] == 10.5


@pytest.mark.asyncio
async def test_run_workflow_no_plan(orchestrator: Orchestrator, tmp_path: Path):
    """Test workflow fails when PLAN.md doesn't exist."""
    result = await orchestrator.run_workflow(
        project_path=tmp_path,
        plan=False,
    )

    assert not result.success
    assert "PLAN.md not found" in result.error


@pytest.mark.asyncio
async def test_run_workflow_with_plan_generation(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan generated",
        metadata={"plan_path": str(tmp_path / "PLAN.md")},
    )

    with patch.object(orchestrator.planner, "execute", new_callable=AsyncMock) as mock_planner:

        def create_plan(*args, **kwargs):
            (tmp_path / "PLAN.md").write_text(sample_plan_content)
            return mock_result

        mock_planner.side_effect = create_plan

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=True,
        )

        assert result.success
        assert result.total_tasks == 2
        assert mock_planner.called


@pytest.mark.asyncio
async def test_run_workflow_plan_exists(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow succeeds when PLAN.md already exists and plan=False."""
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    result = await orchestrator.run_workflow(
        project_path=tmp_path,
        plan=False,
    )

    assert result.success
    assert result.total_tasks == 2


@pytest.mark.asyncio
async def test_run_workflow_plan_generation_failure(
    orchestrator: Orchestrator, tmp_path: Path
):
    """Test workflow fails when plan generation fails."""
    mock_result = AgentResult(
        status=AgentStatus.FAILURE,
        output="",
        metadata={},
        error="LLM call failed",
    )

    with patch.object(orchestrator.planner, "execute", new_callable=AsyncMock) as mock_planner:
        mock_planner.return_value = mock_result

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=True,
        )

        assert not result.success
        assert "Plan generation failed" in result.error


@pytest.mark.asyncio
async def test_run_workflow_template_plan_rejected(
    orchestrator: Orchestrator, tmp_path: Path
):
    """Test that template PLAN.md is rejected when plan=False."""
    (tmp_path / "PLAN.md").write_text(
        "# PLAN.md\n\nRun `sago plan` to generate this file\n"
    )

    result = await orchestrator.run_workflow(
        project_path=tmp_path,
        plan=False,
    )

    assert not result.success
    assert "template" in result.error


@pytest.mark.asyncio
async def test_run_workflow_empty_plan(
    orchestrator: Orchestrator, tmp_path: Path
):
    """Test workflow fails when PLAN.md has no tasks."""
    (tmp_path / "PLAN.md").write_text("# PLAN.md\n\nNo tasks here.\n")

    result = await orchestrator.run_workflow(
        project_path=tmp_path,
        plan=False,
    )

    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
async def test_run_workflow_ignores_extra_kwargs(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test that extra kwargs (from old API) are silently ignored."""
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    result = await orchestrator.run_workflow(
        project_path=tmp_path,
        plan=False,
        execute=True,
        verify=True,
        continue_on_failure=True,
    )

    assert result.success
