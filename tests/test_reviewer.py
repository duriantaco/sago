"""Tests for ReviewerAgent, the post-phase review feedback loop, and judge config."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sago.agents.reviewer import ReviewerAgent
from sago.core.config import Config
from sago.core.parser import MarkdownParser, Phase, Task

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def reviewer(config: Config) -> ReviewerAgent:
    return ReviewerAgent(config=config)


@pytest.fixture
def parser() -> MarkdownParser:
    return MarkdownParser()


@pytest.fixture
def sample_phase(tmp_path: Path) -> Phase:
    """A phase with one task whose file exists on disk."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def hello():\n    return 'hi'\n")
    return Phase(
        name="Phase 1: Foundation",
        description="Set up project structure",
        tasks=[
            Task(
                id="1.1",
                name="Create app module",
                files=["src/app.py"],
                action="Create the app module with a hello function",
                verify='python -c "from src.app import hello"',
                done="Module imports successfully",
                phase_name="Phase 1: Foundation",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# parse_review_prompt
# ---------------------------------------------------------------------------


class TestParseReviewPrompt:
    def test_extracts_review_from_xml_block(self, parser: MarkdownParser) -> None:
        content = """# PLAN.md

```xml
<phases>
    <review>
        Check for code quality and edge cases.
        Focus on DRY violations.
    </review>

    <phase name="Phase 1">
        <task id="1.1">
            <name>Test</name>
            <files>test.py</files>
            <action>Do something detailed enough</action>
            <verify>pytest</verify>
            <done>Tests pass</done>
        </task>
    </phase>
</phases>
```
"""
        result = parser.parse_review_prompt(content)
        assert "code quality" in result
        assert "DRY violations" in result

    def test_returns_empty_when_no_review_tag(self, parser: MarkdownParser) -> None:
        content = """```xml
<phases>
    <phase name="Phase 1">
        <task id="1.1">
            <name>Test</name>
            <files>test.py</files>
            <action>Do something</action>
            <verify>pytest</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```"""
        result = parser.parse_review_prompt(content)
        assert result == ""

    def test_returns_empty_when_no_xml(self, parser: MarkdownParser) -> None:
        content = "# PLAN.md\n\nNo XML here."
        result = parser.parse_review_prompt(content)
        assert result == ""

    def test_returns_empty_on_invalid_xml(self, parser: MarkdownParser) -> None:
        content = "```xml\n<phases><review>broken\n```"
        result = parser.parse_review_prompt(content)
        assert result == ""

    def test_raw_xml_without_code_fence(self, parser: MarkdownParser) -> None:
        content = """<phases>
    <review>Review everything carefully.</review>
    <phase name="P1">
        <task id="1"><name>T</name><files>f.py</files>
        <action>Do something reasonably detailed</action>
        <verify>true</verify><done>ok</done></task>
    </phase>
</phases>"""
        result = parser.parse_review_prompt(content)
        assert "Review everything carefully" in result


# ---------------------------------------------------------------------------
# ReviewerAgent
# ---------------------------------------------------------------------------


class TestReviewerAgent:
    def test_successful_review(
        self, reviewer: ReviewerAgent, sample_phase: Phase, tmp_path: Path
    ) -> None:
        mock_response = {
            "content": "- [WARNING] hello() has no docstring (src/app.py:1)",
            "usage": {"total_tokens": 100},
        }

        with patch.object(reviewer, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = asyncio.run(
                reviewer.execute(
                    {
                        "phase": sample_phase,
                        "project_path": tmp_path,
                        "review_prompt": "Review for quality.",
                    }
                )
            )

        assert result.success
        assert "WARNING" in result.output
        assert result.metadata["phase_name"] == "Phase 1: Foundation"

    def test_llm_error_returns_failure(
        self, reviewer: ReviewerAgent, sample_phase: Phase, tmp_path: Path
    ) -> None:
        with patch.object(reviewer, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = RuntimeError("LLM unavailable")
            result = asyncio.run(
                reviewer.execute(
                    {
                        "phase": sample_phase,
                        "project_path": tmp_path,
                        "review_prompt": "Review for quality.",
                    }
                )
            )

        assert not result.success
        assert "LLM unavailable" in (result.error or "")

    def test_build_review_context_includes_file_contents(
        self, reviewer: ReviewerAgent, sample_phase: Phase, tmp_path: Path
    ) -> None:
        ctx = reviewer._build_review_context(sample_phase, tmp_path)
        assert "Phase 1: Foundation" in ctx
        assert "def hello():" in ctx
        assert "src/app.py" in ctx

    def test_build_review_context_missing_file(
        self, reviewer: ReviewerAgent, tmp_path: Path
    ) -> None:
        phase = Phase(
            name="Phase 1",
            description="",
            tasks=[
                Task(
                    id="1.1",
                    name="Create module",
                    files=["nonexistent.py"],
                    action="Create something detailed enough to validate",
                    verify="true",
                    done="done",
                    phase_name="Phase 1",
                ),
            ],
        )
        ctx = reviewer._build_review_context(phase, tmp_path)
        # File name appears in task listing, but no file contents section for it
        assert "--- nonexistent.py ---" not in ctx

    def test_build_review_messages_structure(
        self, reviewer: ReviewerAgent, sample_phase: Phase, tmp_path: Path
    ) -> None:
        ctx = reviewer._build_review_context(sample_phase, tmp_path)
        messages = reviewer._build_review_messages("Check quality.", ctx, sample_phase)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Check quality." in messages[1]["content"]
        assert "REVIEW INSTRUCTIONS" in messages[1]["content"]


# ---------------------------------------------------------------------------
# Graceful handling: no <review> tag, review failure
# ---------------------------------------------------------------------------


class TestGracefulHandling:
    def test_no_review_tag_means_empty_prompt(self, parser: MarkdownParser) -> None:
        content = """```xml
<phases>
    <phase name="P1">
        <task id="1.1"><name>T</name><files>f.py</files>
        <action>Implement something</action>
        <verify>true</verify><done>ok</done></task>
    </phase>
</phases>
```"""
        prompt = parser.parse_review_prompt(content)
        assert prompt == ""

    def test_reviewer_failure_does_not_raise(
        self, reviewer: ReviewerAgent, sample_phase: Phase, tmp_path: Path
    ) -> None:
        """ReviewerAgent returns FAILURE on LLM error but does not crash."""
        with patch.object(reviewer, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Network error")
            result = asyncio.run(
                reviewer.execute(
                    {
                        "phase": sample_phase,
                        "project_path": tmp_path,
                        "review_prompt": "Review.",
                    }
                )
            )
        assert not result.success
        assert result.error is not None


# ---------------------------------------------------------------------------
# Judge configuration
# ---------------------------------------------------------------------------


class TestJudgeConfig:
    def test_effective_judge_model_defaults_to_llm_model(self) -> None:
        cfg = Config(llm_model="gpt-4o")
        assert cfg.effective_judge_model == "gpt-4o"

    def test_effective_judge_model_override(self) -> None:
        cfg = Config(llm_model="gpt-4o", judge_model="claude-sonnet-4-20250514")
        assert cfg.effective_judge_model == "claude-sonnet-4-20250514"

    def test_judge_prompt_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JUDGE_PROMPT", "Check for security issues.")
        cfg = Config()
        assert cfg.judge_prompt == "Check for security issues."

    def test_judge_prompt_none_by_default(self) -> None:
        cfg = Config()
        assert cfg.judge_prompt is None

    def test_get_judge_api_key_from_keyring(self) -> None:
        cfg = Config(llm_api_key="main-key")
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = "keyring-key"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert cfg.get_judge_api_key() == "keyring-key"
        mock_keyring.get_password.assert_called_once_with("sago", "judge_api_key")

    def test_get_judge_api_key_falls_back_to_env(self) -> None:
        cfg = Config(llm_api_key="main-key", judge_api_key="env-judge-key")
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert cfg.get_judge_api_key() == "env-judge-key"

    def test_get_judge_api_key_falls_back_to_main_key(self) -> None:
        cfg = Config(llm_api_key="main-key", judge_api_key="")
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert cfg.get_judge_api_key() == "main-key"

    def test_get_judge_api_key_keyring_error_falls_back(self) -> None:
        cfg = Config(llm_api_key="main-key", judge_api_key="env-judge-key")
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = Exception("no backend")
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            assert cfg.get_judge_api_key() == "env-judge-key"
