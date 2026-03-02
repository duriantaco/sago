import tempfile
from pathlib import Path

import pytest

from sago.core.config import Config


def test_config_default_values() -> None:
    """Test that config loads with default values."""
    config = Config(_env_file=None)  # type: ignore[call-arg]
    assert config.llm_provider == "anthropic"
    assert config.llm_temperature == 0.1
    assert config.enable_git_commits is True
    assert config.log_level == "INFO"


def test_config_loads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that config loads from environment variables."""
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-3-opus-20240229")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    config = Config()
    assert config.llm_provider == "anthropic"
    assert config.llm_model == "claude-3-opus-20240229"
    assert config.llm_temperature == 0.5
    assert config.log_level == "DEBUG"


def test_config_creates_planning_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        planning_dir = Path(tmpdir) / ".planning"
        config = Config(planning_dir=planning_dir)
        assert config.planning_dir.exists()
        assert config.planning_dir.is_dir()


def test_config_with_env_file(tmp_path: Path) -> None:
    """Test that config loads from .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=azure\nLLM_MODEL=gpt-4\n")

    config = Config(_env_file=env_file)  # type: ignore[call-arg]
    assert config.llm_provider == "azure"
    assert config.llm_model == "gpt-4"
