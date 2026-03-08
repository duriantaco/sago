"""Tests for validation integration in planner and replanner agents."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sago.agents.base import AgentStatus
from sago.agents.planner import PlannerAgent
from sago.agents.replanner import ReplannerAgent
from sago.core.config import Config
from sago.models.execution import ExecutionHistory, ExecutionRecord, VerifierResult

# Valid XML that passes validation
VALID_XML = """<phases>
    <phase name="Phase 1: Setup">
        <description>Set up project</description>
        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module with settings</action>
            <verify>python -c "import config"</verify>
            <done>Config module exists</done>
        </task>
        <task id="1.2">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main entry point</action>
            <verify>python -c "import main"</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>"""

# Invalid XML with duplicate IDs (validation error)
INVALID_XML_DUPLICATE_IDS = """<phases>
    <phase name="Phase 1: Setup">
        <description>Set up project</description>
        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module</action>
            <verify>python -c "import config"</verify>
            <done>Config module exists</done>
        </task>
        <task id="1.1">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main entry point</action>
            <verify>python -c "import main"</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>"""

SAMPLE_PLAN = """# PLAN.md

> **CRITICAL COMPONENT:** This file uses a specific XML schema.

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


@pytest.fixture
def mock_config() -> Config:
    return Config()


@pytest.fixture
def planner(mock_config: Config) -> PlannerAgent:
    return PlannerAgent(config=mock_config)


@pytest.fixture
def replanner(mock_config: Config) -> ReplannerAgent:
    return ReplannerAgent(config=mock_config)


@pytest.fixture
def project_with_plan(tmp_path: Path) -> Path:
    (tmp_path / "PLAN.md").write_text(SAMPLE_PLAN)
    (tmp_path / "STATE.md").write_text(SAMPLE_STATE)
    (tmp_path / "PROJECT.md").write_text("# My Project\nA test project.")
    (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* [ ] **REQ-1:** Do stuff")
    return tmp_path


class TestPlannerValidation:
    @pytest.mark.asyncio
    async def test_valid_plan_succeeds(self, planner: PlannerAgent, tmp_path: Path) -> None:
        """Planner should succeed when LLM produces valid XML."""
        (tmp_path / "PROJECT.md").write_text("# Test Project")
        (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* Do stuff")

        with patch.object(planner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": VALID_XML}

            result = await planner.execute({"project_path": tmp_path})

            assert result.status == AgentStatus.SUCCESS
            assert mock_llm.call_count == 1  # No retry needed

    @pytest.mark.asyncio
    async def test_invalid_plan_retries_once(self, planner: PlannerAgent, tmp_path: Path) -> None:
        """Planner should retry once when LLM produces invalid XML."""
        (tmp_path / "PROJECT.md").write_text("# Test Project")
        (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* Do stuff")

        with patch.object(planner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            # First call returns invalid XML, second returns valid
            mock_llm.side_effect = [
                {"content": INVALID_XML_DUPLICATE_IDS},
                {"content": VALID_XML},
            ]

            result = await planner.execute({"project_path": tmp_path})

            assert result.status == AgentStatus.SUCCESS
            assert mock_llm.call_count == 2  # Initial + retry

    @pytest.mark.asyncio
    async def test_invalid_plan_fails_after_retry(
        self, planner: PlannerAgent, tmp_path: Path
    ) -> None:
        """Planner should fail if retry also produces invalid XML."""
        (tmp_path / "PROJECT.md").write_text("# Test Project")
        (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n* Do stuff")

        with patch.object(planner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            # Both calls return invalid XML
            mock_llm.return_value = {"content": INVALID_XML_DUPLICATE_IDS}

            result = await planner.execute({"project_path": tmp_path})

            assert result.status == AgentStatus.FAILURE
            assert "validation errors" in (result.error or "").lower()

    def test_validate_plan_semantics(self, planner: PlannerAgent) -> None:
        """Semantic validation should catch errors in parsed plan."""
        result = planner._validate_plan_semantics(VALID_XML)
        assert result.valid

    def test_validate_plan_semantics_duplicate_ids(self, planner: PlannerAgent) -> None:
        """Semantic validation should catch duplicate IDs."""
        result = planner._validate_plan_semantics(INVALID_XML_DUPLICATE_IDS)
        assert not result.valid
        assert any(i.code == "DUPLICATE_ID" for i in result.errors)

    def test_format_validation_errors(self, planner: PlannerAgent) -> None:
        """Error formatting should include issue details."""
        result = planner._validate_plan_semantics(INVALID_XML_DUPLICATE_IDS)
        feedback = planner._format_validation_errors(result)
        assert "DUPLICATE_ID" in feedback
        assert "must be fixed" in feedback


class TestReplannerValidation:
    @pytest.mark.asyncio
    async def test_valid_replan_succeeds(
        self, replanner: ReplannerAgent, project_with_plan: Path
    ) -> None:
        """Replanner should succeed when LLM produces valid XML."""
        with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": VALID_XML}

            result = await replanner.execute(
                {"project_path": project_with_plan, "feedback": "add logging"}
            )

            assert result.status == AgentStatus.SUCCESS
            assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_invalid_replan_retries(
        self, replanner: ReplannerAgent, project_with_plan: Path
    ) -> None:
        """Replanner should retry when LLM produces invalid XML."""
        with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [
                {"content": INVALID_XML_DUPLICATE_IDS},
                {"content": VALID_XML},
            ]

            result = await replanner.execute(
                {"project_path": project_with_plan, "feedback": "add logging"}
            )

            assert result.status == AgentStatus.SUCCESS
            assert mock_llm.call_count == 2


class TestExecutionHistoryInReplan:
    @pytest.mark.asyncio
    async def test_execution_history_included_in_prompt(
        self, replanner: ReplannerAgent, project_with_plan: Path
    ) -> None:
        """Execution history should appear in the replan prompt."""
        history = ExecutionHistory(
            records=[
                ExecutionRecord(
                    task_id="1.2",
                    attempt=1,
                    verifier_result=VerifierResult(
                        task_id="1.2",
                        command="pytest",
                        exit_code=1,
                        stderr="ImportError: No module named 'config'",
                        failure_category="import_error",
                    ),
                ),
                ExecutionRecord(
                    task_id="1.2",
                    attempt=2,
                    verifier_result=VerifierResult(
                        task_id="1.2",
                        command="pytest",
                        exit_code=1,
                        stderr="AssertionError: expected True",
                        failure_category="assertion_failure",
                    ),
                ),
            ]
        )

        with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": VALID_XML}

            await replanner.execute(
                {
                    "project_path": project_with_plan,
                    "feedback": "fix failing task",
                    "execution_history": history,
                }
            )

            call_args = mock_llm.call_args[0][0]
            user_msg = call_args[1]["content"]
            assert "Execution History" in user_msg
            assert "Task 1.2: FAILED (2 attempt(s))" in user_msg
            assert "assertion_failure" in user_msg

    @pytest.mark.asyncio
    async def test_no_execution_history(
        self, replanner: ReplannerAgent, project_with_plan: Path
    ) -> None:
        """Replan without execution history should not include the section."""
        with patch.object(replanner, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {"content": VALID_XML}

            await replanner.execute(
                {"project_path": project_with_plan, "feedback": "add logging"}
            )

            call_args = mock_llm.call_args[0][0]
            user_msg = call_args[1]["content"]
            assert "Execution History" not in user_msg

    def test_build_execution_summary(self, replanner: ReplannerAgent) -> None:
        """Execution summary should format failure details."""
        history = ExecutionHistory(
            records=[
                ExecutionRecord(
                    task_id="1.1",
                    attempt=1,
                    verifier_result=VerifierResult(
                        task_id="1.1",
                        command="pytest",
                        exit_code=1,
                        stderr="SyntaxError: invalid syntax",
                        failure_category="syntax_error",
                    ),
                ),
            ]
        )
        summary = replanner._build_execution_summary(history)
        assert "Task 1.1: FAILED" in summary
        assert "syntax_error" in summary
        assert "SyntaxError" in summary

    def test_build_execution_summary_none(self, replanner: ReplannerAgent) -> None:
        """None history should return empty string."""
        assert replanner._build_execution_summary(None) == ""

    def test_build_execution_summary_empty(self, replanner: ReplannerAgent) -> None:
        """Empty history should return empty string."""
        assert replanner._build_execution_summary(ExecutionHistory()) == ""
