"""Tests for orchestrator."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sago.agents.base import AgentResult, AgentStatus
from sago.agents.orchestrator import Orchestrator, TaskExecution, WorkflowResult
from sago.core.config import Config
from sago.core.parser import Phase, Task


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    """Create mock config."""
    return Config()


@pytest.fixture
def sample_plan_content() -> str:
    """Create sample PLAN.md content."""
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
    """Create orchestrator instance."""
    return Orchestrator(config=mock_config)


def test_orchestrator_initialization(orchestrator: Orchestrator):
    """Test orchestrator initialization."""
    assert orchestrator is not None
    assert orchestrator.planner is not None
    assert orchestrator.executor is not None
    assert orchestrator.verifier is not None
    assert orchestrator.dependency_resolver is not None


def test_task_execution_success():
    """Test TaskExecution with successful execution."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    exec_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Task executed",
        metadata={},
        error=None,
    )

    verify_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Task verified",
        metadata={},
        error=None,
    )

    task_exec = TaskExecution(
        task=task,
        execution_result=exec_result,
        verification_result=verify_result,
        start_time=datetime.now(),
        end_time=datetime.now(),
    )

    assert task_exec.success
    assert task_exec.duration >= 0


def test_task_execution_failure():
    """Test TaskExecution with failure."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    exec_result = AgentResult(
        status=AgentStatus.FAILURE,
        output="",
        metadata={},
        error="Execution failed",
    )

    task_exec = TaskExecution(
        task=task,
        execution_result=exec_result,
        start_time=datetime.now(),
        end_time=datetime.now(),
    )

    assert not task_exec.success


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
        plan=False,  # Don't generate plan
        execute=True,
    )

    assert not result.success
    assert "PLAN.md not found" in result.error


@pytest.mark.asyncio
async def test_run_workflow_with_plan_generation(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow with plan generation."""
    # Mock planner to return success
    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan generated",
        metadata={"plan_path": str(tmp_path / "PLAN.md")},
    )

    with patch.object(orchestrator.planner, "execute", new_callable=AsyncMock) as mock_planner:
        mock_planner.return_value = mock_result

        # Create PLAN.md after planner runs
        def create_plan(*args, **kwargs):
            (tmp_path / "PLAN.md").write_text(sample_plan_content)
            return mock_result

        mock_planner.side_effect = create_plan

        # Mock executor and verifier
        with patch.object(
            orchestrator.executor, "execute", new_callable=AsyncMock
        ) as mock_executor, patch.object(
            orchestrator.verifier, "execute", new_callable=AsyncMock
        ) as mock_verifier:

            mock_executor.return_value = AgentResult(
                status=AgentStatus.SUCCESS, output="Executed", metadata={}
            )
            mock_verifier.return_value = AgentResult(
                status=AgentStatus.SUCCESS, output="Verified", metadata={}
            )

            result = await orchestrator.run_workflow(
                project_path=tmp_path,
                plan=True,
                execute=True,
                verify=True,
            )

            assert result.success
            assert mock_planner.called


@pytest.mark.asyncio
async def test_run_workflow_plan_exists(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow when PLAN.md already exists."""
    # Create PLAN.md
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    # Mock executor and verifier
    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor, patch.object(
        orchestrator.verifier, "execute", new_callable=AsyncMock
    ) as mock_verifier:

        mock_executor.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Executed", metadata={}
        )
        mock_verifier.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Verified", metadata={}
        )

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=False,  # Don't regenerate
            execute=True,
            verify=True,
        )

        assert result.success
        assert result.total_tasks == 2  # Two tasks in sample plan
        assert result.completed_tasks == 2


@pytest.mark.asyncio
async def test_execute_single_task_with_retry(orchestrator: Orchestrator):
    """Test single task execution with retry."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    # First attempt fails, second succeeds
    fail_result = AgentResult(
        status=AgentStatus.FAILURE, output="", error="First attempt failed", metadata={}
    )

    success_result = AgentResult(
        status=AgentStatus.SUCCESS, output="Success", error=None, metadata={}
    )

    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor, patch.object(
        orchestrator.verifier, "execute", new_callable=AsyncMock
    ) as mock_verifier:

        mock_executor.side_effect = [fail_result, success_result]
        mock_verifier.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Verified", metadata={}
        )

        task_exec = await orchestrator._execute_single_task(
            task, Path("."), verify=True, max_retries=2
        )

        assert task_exec.success
        assert task_exec.retry_count == 1  # One retry
        assert mock_executor.call_count == 2


@pytest.mark.asyncio
async def test_execute_single_task_max_retries_exceeded(orchestrator: Orchestrator):
    """Test single task execution when max retries exceeded."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    # Always fail
    fail_result = AgentResult(
        status=AgentStatus.FAILURE, output="", error="Task failed", metadata={}
    )

    with patch.object(orchestrator.executor, "execute", new_callable=AsyncMock) as mock_executor:
        mock_executor.return_value = fail_result

        task_exec = await orchestrator._execute_single_task(
            task, Path("."), verify=False, max_retries=2
        )

        assert not task_exec.success
        assert task_exec.retry_count == 2
        assert mock_executor.call_count == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_execute_wave_parallel(orchestrator: Orchestrator):
    """Test executing wave of tasks in parallel."""
    tasks = [
        Task(
            id="1.1",
            name="Task A",
            phase_name="Phase 1",
            files=["a.py"],
            action="Create A",
            verify="python -c 'import a'",
            done="A exists",
        ),
        Task(
            id="1.2",
            name="Task B",
            phase_name="Phase 1",
            files=["b.py"],
            action="Create B",
            verify="python -c 'import b'",
            done="B exists",
        ),
    ]

    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor, patch.object(
        orchestrator.verifier, "execute", new_callable=AsyncMock
    ) as mock_verifier:

        mock_executor.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Executed", metadata={}
        )
        mock_verifier.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Verified", metadata={}
        )

        results = await orchestrator._execute_wave(tasks, Path("."), verify=True, max_retries=1)

        assert len(results) == 2
        assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_update_state(orchestrator: Orchestrator, tmp_path: Path):
    """Test STATE.md update."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    await orchestrator._update_state(tmp_path, task, success=True)

    state_path = tmp_path / "STATE.md"
    assert state_path.exists()

    content = state_path.read_text()
    assert "1.1" in content
    assert "Test task" in content
    assert "✓" in content


@pytest.mark.asyncio
async def test_update_state_with_error(orchestrator: Orchestrator, tmp_path: Path):
    """Test STATE.md update with error."""
    task = Task(
        id="1.1",
        name="Test task",
        phase_name="Phase 1",
        files=["test.py"],
        action="Test action",
        verify="python test.py",
        done="Task complete",
    )

    await orchestrator._update_state(tmp_path, task, success=False, error="Task failed")

    state_path = tmp_path / "STATE.md"
    content = state_path.read_text()

    assert "✗" in content
    assert "Task failed" in content


@pytest.mark.asyncio
async def test_workflow_continue_on_failure(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow continues on failure when flag is set."""
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    # First task fails, second succeeds
    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor, patch.object(
        orchestrator.verifier, "execute", new_callable=AsyncMock
    ) as mock_verifier:

        mock_executor.side_effect = [
            AgentResult(status=AgentStatus.FAILURE, output="", error="Failed", metadata={}),
            AgentResult(status=AgentStatus.SUCCESS, output="Success", metadata={}),
        ]

        mock_verifier.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Verified", metadata={}
        )

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=False,
            execute=True,
            verify=True,
            continue_on_failure=True,
        )

        assert not result.success  # Overall fails
        assert result.failed_tasks == 1
        assert result.completed_tasks == 1  # Second task completed


@pytest.mark.asyncio
async def test_workflow_stop_on_failure(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow stops on first failure."""
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor:

        mock_executor.return_value = AgentResult(
            status=AgentStatus.FAILURE, output="", error="Failed", metadata={}
        )

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=False,
            execute=True,
            verify=False,
            continue_on_failure=False,
        )

        assert not result.success
        assert result.failed_tasks >= 1
        assert result.skipped_tasks >= 0


@pytest.mark.asyncio
async def test_workflow_without_verification(
    orchestrator: Orchestrator, tmp_path: Path, sample_plan_content: str
):
    """Test workflow without verification step."""
    (tmp_path / "PLAN.md").write_text(sample_plan_content)

    with patch.object(
        orchestrator.executor, "execute", new_callable=AsyncMock
    ) as mock_executor, patch.object(
        orchestrator.verifier, "execute", new_callable=AsyncMock
    ) as mock_verifier:

        mock_executor.return_value = AgentResult(
            status=AgentStatus.SUCCESS, output="Executed", metadata={}
        )

        result = await orchestrator.run_workflow(
            project_path=tmp_path,
            plan=False,
            execute=True,
            verify=False,  # Skip verification
        )

        assert result.success
        assert not mock_verifier.called  # Verifier should not be called
