from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sago.agents.base import AgentResult, AgentStatus
from sago.agents.orchestrator import Orchestrator
from sago.agents.replanner import ReplannerAgent
from sago.core.config import Config  # noqa: I001

SAMPLE_PLAN = """# PLAN.md

> **CRITICAL COMPONENT:** This file uses a specific XML schema to force the AI into "Atomic Task" mode.

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

SAMPLE_STATE = """# STATE.md

## Completed Tasks
[✓] 1.1: Create config — Config module exists

## Failed Tasks
"""

UPDATED_XML = """<phases>
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
            <name>Create main with CLI</name>
            <files>main.py</files>
            <action>Create main module with CLI support using typer</action>
            <verify>python -c "import main"</verify>
            <done>Main module with CLI exists</done>
        </task>

        <task id="1.3">
            <name>Add rate limiting</name>
            <files>rate_limit.py</files>
            <action>Create rate limiting middleware</action>
            <verify>python -c "import rate_limit"</verify>
            <done>Rate limiter works</done>
        </task>
    </phase>
</phases>"""


@pytest.fixture
def mock_config() -> Config:
    return Config()


@pytest.fixture
def replanner(mock_config: Config) -> ReplannerAgent:
    return ReplannerAgent(config=mock_config)


@pytest.fixture
def project_with_plan(tmp_path: Path) -> Path:
    """Create a project directory with PLAN.md and STATE.md."""
    (tmp_path / "PLAN.md").write_text(SAMPLE_PLAN)
    (tmp_path / "STATE.md").write_text(SAMPLE_STATE)
    (tmp_path / "PROJECT.md").write_text("# My Project\nA test project.")
    (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* [ ] **REQ-1:** Do stuff")
    return tmp_path


@pytest.mark.asyncio
async def test_replan_prompt_includes_current_xml(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should include the current plan XML."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "<task id=" in user_msg
        assert "Create config" in user_msg


@pytest.mark.asyncio
async def test_replan_prompt_includes_state_summary(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should include task state summary."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "1 done" in user_msg
        assert "DONE" in user_msg


@pytest.mark.asyncio
async def test_replan_system_prompt_preserves_done(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """System prompt should instruct preserving completed tasks."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        system_msg = call_args[0]["content"]
        assert "DONE" in system_msg
        assert "preserved" in system_msg.lower()


@pytest.mark.asyncio
async def test_replan_prompt_includes_feedback(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should include the user's feedback."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "add rate limiting" in user_msg


@pytest.mark.asyncio
async def test_replan_invalid_xml_raises(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Invalid XML from LLM should raise ValueError."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "Here is the updated plan but no XML."}

        result = await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        assert result.status == AgentStatus.FAILURE
        assert result.error is not None


@pytest.mark.asyncio
async def test_replan_missing_plan_raises(replanner: ReplannerAgent, tmp_path: Path) -> None:
    """Missing PLAN.md should raise an error."""
    result = await replanner.execute({
        "project_path": tmp_path,
        "feedback": "add rate limiting",
    })

    assert result.status == AgentStatus.FAILURE
    assert "PLAN.md not found" in (result.error or "")


@pytest.mark.asyncio
async def test_replan_saves_updated_plan(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan should save the updated XML to PLAN.md."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        result = await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        assert result.status == AgentStatus.SUCCESS
        new_content = (project_with_plan / "PLAN.md").read_text()
        assert "rate limiting" in new_content.lower()
        assert "ReplannerAgent" in new_content


@pytest.mark.asyncio
async def test_orchestrator_replan_workflow(tmp_path: Path) -> None:
    """Test the orchestrator's run_replan_workflow method."""
    (tmp_path / "PLAN.md").write_text(SAMPLE_PLAN)
    (tmp_path / "STATE.md").write_text(SAMPLE_STATE)

    orchestrator = Orchestrator(config=Config())

    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan updated",
        metadata={"plan_path": str(tmp_path / "PLAN.md")},
    )

    with patch.object(orchestrator.replanner, "execute", new_callable=AsyncMock) as mock_replan:

        def do_replan(*args: object, **kwargs: object) -> AgentResult:
            # Write updated PLAN.md (simulating what the agent does)
            updated = SAMPLE_PLAN.replace("Create main", "Create main with CLI")
            (tmp_path / "PLAN.md").write_text(updated)
            return mock_result

        mock_replan.side_effect = do_replan

        result = await orchestrator.run_replan_workflow(
            project_path=tmp_path,
            feedback="add CLI support",
        )

        assert result.success
        assert mock_replan.called


@pytest.mark.asyncio
async def test_orchestrator_replan_failure(tmp_path: Path) -> None:
    """Test replan workflow handles agent failure."""
    (tmp_path / "PLAN.md").write_text(SAMPLE_PLAN)

    orchestrator = Orchestrator(config=Config())

    mock_result = AgentResult(
        status=AgentStatus.FAILURE,
        output="",
        metadata={},
        error="LLM call failed",
    )

    with patch.object(orchestrator.replanner, "execute", new_callable=AsyncMock) as mock_replan:
        mock_replan.return_value = mock_result

        result = await orchestrator.run_replan_workflow(
            project_path=tmp_path,
            feedback="add CLI support",
        )

        assert not result.success
        assert "Replan failed" in (result.error or "")


def test_orchestrator_has_replanner() -> None:
    """Test that Orchestrator initializes a ReplannerAgent."""
    orchestrator = Orchestrator(config=Config())
    assert hasattr(orchestrator, "replanner")
    assert isinstance(orchestrator.replanner, ReplannerAgent)


def test_orchestrator_has_reviewer() -> None:
    """Test that Orchestrator initializes a ReviewerAgent."""
    from sago.agents.reviewer import ReviewerAgent

    orchestrator = Orchestrator(config=Config())
    assert hasattr(orchestrator, "reviewer")
    assert isinstance(orchestrator.reviewer, ReviewerAgent)


@pytest.mark.asyncio
async def test_replan_prompt_includes_review_context(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should include review context when provided."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "fix the issues",
            "review_context": "[WARNING] config.py missing DB_URL validation",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Phase Review Feedback" in user_msg
        assert "config.py missing DB_URL validation" in user_msg


@pytest.mark.asyncio
async def test_replan_prompt_without_review_context(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should not include review section when no review context."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Phase Review Feedback" not in user_msg


@pytest.mark.asyncio
async def test_replan_loads_repo_map(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan should include repo map in project context."""
    # Create a Python file so the repo map has something to find
    (project_with_plan / "config.py").write_text("class AppConfig:\n    pass\n")

    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "add rate limiting",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "REPO_MAP" in user_msg
        assert "AppConfig" in user_msg


@pytest.mark.asyncio
async def test_replan_corrective_task_rule_in_prompt(
    replanner: ReplannerAgent, project_with_plan: Path
) -> None:
    """Replan prompt should include the corrective task rule (rule 9)."""
    with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": UPDATED_XML}

        await replanner.execute({
            "project_path": project_with_plan,
            "feedback": "fix issues",
            "review_context": "some review feedback",
        })

        call_args = mock_llm.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "corrective tasks" in user_msg.lower()


@pytest.mark.asyncio
async def test_orchestrator_run_review(tmp_path: Path) -> None:
    """Test the orchestrator's run_review method."""
    from sago.core.parser import Phase, Task

    (tmp_path / "PROJECT.md").write_text("# Test\nA test project.")
    (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* [ ] **REQ-1:** Do stuff")
    (tmp_path / "config.py").write_text("DB_URL = 'sqlite:///test.db'\n")

    orchestrator = Orchestrator(config=Config())

    phase = Phase(
        name="Phase 1: Foundation",
        description="Set up project",
        tasks=[
            Task(
                id="1.1", name="Create config", files=["config.py"],
                action="Create config", verify="python -c 'import config'",
                done="Config exists", phase_name="Phase 1: Foundation",
            ),
        ],
    )

    mock_review = AgentResult(
        status=AgentStatus.SUCCESS,
        output="[WARNING] config.py missing validation",
        metadata={"phase_name": "Phase 1: Foundation"},
    )

    with patch.object(orchestrator.reviewer, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = mock_review

        result = await orchestrator.run_review(
            tmp_path, phase, "Review for correctness"
        )

        assert result.success
        assert "missing validation" in result.output
        mock_exec.assert_called_once()
        ctx = mock_exec.call_args[0][0]
        assert ctx["phase"] is phase
        assert ctx["review_prompt"] == "Review for correctness"


@pytest.mark.asyncio
async def test_orchestrator_replan_passes_review_context(tmp_path: Path) -> None:
    """Test that run_replan_workflow passes review_context to replanner."""
    (tmp_path / "PLAN.md").write_text(SAMPLE_PLAN)
    (tmp_path / "STATE.md").write_text(SAMPLE_STATE)

    orchestrator = Orchestrator(config=Config())

    mock_result = AgentResult(
        status=AgentStatus.SUCCESS,
        output="Plan updated",
        metadata={"plan_path": str(tmp_path / "PLAN.md")},
    )

    with patch.object(orchestrator.replanner, "execute", new_callable=AsyncMock) as mock_replan:

        def do_replan(_context: dict) -> AgentResult:
            (tmp_path / "PLAN.md").write_text(
                SAMPLE_PLAN.replace("Create main", "Create main with CLI")
            )
            return mock_result

        mock_replan.side_effect = do_replan

        result = await orchestrator.run_replan_workflow(
            project_path=tmp_path,
            feedback="fix issues",
            review_context="[WARNING] missing validation",
            repo_map="config.py:\n  class AppConfig\n",
        )

        assert result.success
        ctx = mock_replan.call_args[0][0]
        assert ctx["review_context"] == "[WARNING] missing validation"
        assert ctx["repo_map"] == "config.py:\n  class AppConfig\n"
