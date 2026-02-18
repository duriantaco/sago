"""Tests for executor and verifier agents."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sago.agents.base import AgentResult, AgentStatus
from sago.agents.executor import ExecutorAgent
from sago.agents.verifier import VerifierAgent
from sago.core.config import Config
from sago.core.parser import Task


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def sample_task() -> Task:
    return Task(
        id="1.1",
        name="Create module",
        files=["src/app.py"],
        action="Create the app module",
        verify="python -c \"import src.app\"",
        done="Module imports successfully",
        phase_name="Phase 1",
    )


class TestExecutorParseCode:

    @pytest.fixture
    def executor(self, config: Config) -> ExecutorAgent:
        return ExecutorAgent(config=config)

    def test_standard_format(self, executor: ExecutorAgent) -> None:
        content = """Here's the code:

=== FILE: src/app.py ===
```python
def main():
    print("hello")
```
"""
        changes = executor._parse_generated_code(content)
        assert "src/app.py" in changes
        assert 'def main():' in changes["src/app.py"]

    def test_multiple_files(self, executor: ExecutorAgent) -> None:
        content = """
=== FILE: src/app.py ===
```python
x = 1
```

=== FILE: src/utils.py ===
```python
y = 2
```
"""
        changes = executor._parse_generated_code(content)
        assert len(changes) == 2
        assert "src/app.py" in changes
        assert "src/utils.py" in changes

    def test_no_language_hint(self, executor: ExecutorAgent) -> None:
        content = """
=== FILE: config.json ===
```
{"key": "value"}
```
"""
        changes = executor._parse_generated_code(content)
        assert "config.json" in changes
        assert '"key": "value"' in changes["config.json"]

    def test_no_match_raises_error(self, executor: ExecutorAgent) -> None:
        with pytest.raises(ValueError, match="LLM response did not contain any files"):
            executor._parse_generated_code("just some text without code blocks")

    def test_empty_code_block_not_included(self, executor: ExecutorAgent) -> None:
        content = """
=== FILE: src/app.py ===
```python
actual_code = True
```

=== FILE: src/empty.py ===
```python
```
"""
        changes = executor._parse_generated_code(content)
        assert "src/app.py" in changes


class TestExecutorApplyChanges:
    """Tests for ExecutorAgent._apply_changes."""

    @pytest.fixture
    def executor(self, config: Config) -> ExecutorAgent:
        return ExecutorAgent(config=config)

    def test_creates_file(self, executor: ExecutorAgent, tmp_path: Path) -> None:
        changes = {"src/app.py": "print('hello')"}
        executor._apply_changes(changes, tmp_path)
        assert (tmp_path / "src" / "app.py").exists()
        assert (tmp_path / "src" / "app.py").read_text() == "print('hello')"

    def test_creates_nested_directories(self, executor: ExecutorAgent, tmp_path: Path) -> None:
        changes = {"a/b/c/d.py": "x = 1"}
        executor._apply_changes(changes, tmp_path)
        assert (tmp_path / "a" / "b" / "c" / "d.py").exists()

    def test_overwrites_existing_file(self, executor: ExecutorAgent, tmp_path: Path) -> None:
        existing = tmp_path / "file.py"
        existing.write_text("old content")
        executor._apply_changes({"file.py": "new content"}, tmp_path)
        assert existing.read_text() == "new content"


# =============================================================================
# Verifier: _run_verification
# =============================================================================


class TestVerifierRunVerification:
    """Tests for VerifierAgent._run_verification."""

    @pytest.fixture
    def verifier(self, config: Config) -> VerifierAgent:
        return VerifierAgent(config=config)

    def test_success_command(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="python3 -c \"print('ok')\"", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is True
        assert result["exit_code"] == 0

    def test_failing_command(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="python3 -c \"raise SystemExit(1)\"", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is False
        assert result["exit_code"] == 1

    def test_empty_verify_command_succeeds(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is True
        assert "No verification command" in result["stdout"]

    def test_whitespace_verify_command_succeeds(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="   ", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is True

    def test_invalid_command_syntax(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        """shlex.split should handle malformed commands gracefully."""
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="echo 'unterminated string", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is False
        assert "Invalid command syntax" in result["stderr"]

    def test_timeout_returns_failure(self, tmp_path: Path) -> None:
        """Commands exceeding timeout should fail gracefully."""
        short_timeout_config = Config()
        # Override verify_timeout via model_copy
        short_timeout_config = short_timeout_config.model_copy(update={"verify_timeout": 1})
        verifier = VerifierAgent(config=short_timeout_config)

        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="python3 -c \"import time; time.sleep(10)\"", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert result["success"] is False
        assert "timed out" in result["stderr"].lower()

    def test_captures_stdout(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="python3 -c \"print('test_output')\"", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert "test_output" in result["stdout"]

    def test_captures_stderr(self, verifier: VerifierAgent, tmp_path: Path) -> None:
        task = Task(
            id="1.1", name="test", files=[], action="",
            verify="python3 -c \"import sys; sys.stderr.write('err_out')\"", done="", phase_name="",
        )
        result = asyncio.run(verifier._run_verification(task, tmp_path))
        assert "err_out" in result["stderr"]
