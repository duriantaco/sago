"""Tests for self-healing agent."""

from unittest.mock import AsyncMock, patch

import pytest

from sago.agents.self_healing import SelfHealingAgent
from sago.core.config import Config
from sago.core.parser import Task


@pytest.fixture
def agent() -> SelfHealingAgent:
    """Create a SelfHealingAgent with default config."""
    return SelfHealingAgent(config=Config())


@pytest.fixture
def sample_task() -> Task:
    """Create a sample task for testing."""
    return Task(
        id="1.1",
        name="Create config module",
        files=["src/config.py"],
        action="Create a config module",
        verify="python -c 'import config'",
        done="Config module imports",
        phase_name="Phase 1",
    )


# --- Error classification ---


class TestClassifyError:
    """Tests for _classify_error method."""

    def test_import_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("ModuleNotFoundError: No module named 'foo'") == "import_error"

    def test_import_keyword(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("ImportError: cannot import name 'bar'") == "import_error"

    def test_syntax_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("SyntaxError: invalid syntax") == "syntax_error"

    def test_name_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("NameError: name 'x' is not defined") == "name_error"

    def test_attribute_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("AttributeError: 'str' has no attribute 'foo'") == "name_error"

    def test_type_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("TypeError: expected str, got int") == "type_error"

    def test_indentation_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("IndentationError: unexpected indent") == "indentation_error"

    def test_assertion_failure(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("AssertionError: 1 != 2") == "test_failure"

    def test_test_failed(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("FAILED tests/test_foo.py::test_bar") == "test_failure"

    def test_unknown_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("Something completely unexpected happened") == "unknown_error"

    def test_empty_error(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("") == "unknown_error"

    def test_case_insensitive(self, agent: SelfHealingAgent) -> None:
        assert agent._classify_error("SYNTAXERROR: bad code") == "syntax_error"

    def test_import_takes_priority_over_name(self, agent: SelfHealingAgent) -> None:
        """Import check comes before name check, so 'import' in message wins."""
        result = agent._classify_error("NameError while importing module")
        # Contains both "import" and "nameerror" -- import check is first
        assert result == "import_error"


# --- Should attempt fix ---


class TestShouldAttemptFix:
    """Tests for should_attempt_fix method."""

    def test_import_error_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        assert agent.should_attempt_fix("ImportError: no module named foo", sample_task) is True

    def test_syntax_error_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        assert agent.should_attempt_fix("SyntaxError: invalid syntax", sample_task) is True

    def test_type_error_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        assert agent.should_attempt_fix("TypeError: bad argument", sample_task) is True

    def test_assertion_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        assert agent.should_attempt_fix("FAILED tests/test_foo.py - assert x == y", sample_task) is True

    def test_short_unknown_error_not_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        """Errors < 20 chars without known keywords are skipped."""
        assert agent.should_attempt_fix("error occurred", sample_task) is False

    def test_long_unknown_error_not_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        """Long errors without any known keywords are not fixable either."""
        assert agent.should_attempt_fix("a" * 30, sample_task) is False

    def test_empty_error_not_fixable(self, agent: SelfHealingAgent, sample_task: Task) -> None:
        assert agent.should_attempt_fix("", sample_task) is False


# --- Fix prompt generation ---


class TestBuildFixPrompt:
    """Tests for _build_fix_prompt method."""

    def test_known_error_types_have_prompts(self, agent: SelfHealingAgent) -> None:
        known_types = [
            "import_error", "syntax_error", "name_error",
            "type_error", "indentation_error", "test_failure",
        ]
        for error_type in known_types:
            prompt = agent._build_fix_prompt(error_type)
            assert len(prompt) > 50, f"Prompt for {error_type} is too short"

    def test_unknown_type_gets_generic_prompt(self, agent: SelfHealingAgent) -> None:
        prompt = agent._build_fix_prompt("unknown_error")
        assert "Analyze the error" in prompt

    def test_prompts_are_distinct(self, agent: SelfHealingAgent) -> None:
        """Each error type gets a different prompt."""
        prompts = {agent._build_fix_prompt(t) for t in ["import_error", "syntax_error", "type_error"]}
        assert len(prompts) == 3


# --- Fix parsing ---


class TestParseFix:
    """Tests for _parse_fix method."""

    def test_parses_standard_format(self, agent: SelfHealingAgent) -> None:
        content = """Here's the fix:

=== FILE: src/config.py ===
```python
print("fixed")
```
"""
        fixes = agent._parse_fix(content)
        assert "src/config.py" in fixes
        assert fixes["src/config.py"] == 'print("fixed")'

    def test_parses_multiple_files(self, agent: SelfHealingAgent) -> None:
        content = """
=== FILE: a.py ===
```python
x = 1
```

=== FILE: b.py ===
```python
y = 2
```
"""
        fixes = agent._parse_fix(content)
        assert len(fixes) == 2
        assert "a.py" in fixes
        assert "b.py" in fixes

    def test_no_match_returns_empty(self, agent: SelfHealingAgent) -> None:
        fixes = agent._parse_fix("no code blocks here")
        assert fixes == {}
