import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Provider-specific env var names that litellm also recognises
_PROVIDER_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_API_KEY",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def find_dotenv(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) looking for a .env file.

    Returns the first `.env` path found, or ``None``.
    """
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _read_dotenv_key(key: str, env_path: Path | None = None) -> str:
    """Read a single key from .env without loading everything into os.environ."""
    if env_path is None:
        env_path = find_dotenv()
    if env_path is None or not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip("'\"")
    return ""


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv() or ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: str = Field(
        default="anthropic",
        description="LLM provider (openai, anthropic, azure, etc.)",
    )
    llm_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model name to use for AI operations",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for LLM provider",
    )

    @model_validator(mode="after")
    def _resolve_api_key(self) -> "Config":
        """Fall back to provider-specific env vars (e.g. OPENAI_API_KEY) if LLM_API_KEY is empty."""
        if self.llm_api_key:
            return self
        env_var = _PROVIDER_ENV_KEYS.get(self.llm_provider, "")
        if env_var:
            value = os.environ.get(env_var, "")
            if not value:
                # Also check the .env file values that pydantic loaded but didn't map
                # pydantic-settings with extra="ignore" drops unknown keys, so we read
                # the .env manually for provider keys
                value = _read_dotenv_key(env_var, find_dotenv())
            if value:
                self.llm_api_key = value
        return self

    planner_model: str | None = Field(
        default=None,
        description="Override model for the planner agent (falls back to llm_model)",
    )
    executor_model: str | None = Field(
        default=None,
        description="Override model for the executor agent (falls back to llm_model)",
    )
    judge_model: str | None = Field(
        default=None,
        description="Override model for the judge/reviewer agent (falls back to llm_model)",
    )
    judge_prompt: str | None = Field(
        default=None,
        description="Custom review prompt for the judge agent",
    )
    judge_api_key: str = Field(
        default="",
        description="API key for the judge model (fallback if keyring unavailable)",
    )

    @property
    def effective_planner_model(self) -> str:
        """Model to use for the planner agent."""
        return self.planner_model or self.llm_model

    @property
    def effective_executor_model(self) -> str:
        """Model to use for the executor agent."""
        return self.executor_model or self.llm_model

    @property
    def effective_judge_model(self) -> str:
        """Model to use for the judge/reviewer agent."""
        return self.judge_model or self.llm_model

    def get_judge_api_key(self) -> str:
        """Resolve API key for judge: keyring -> judge_api_key env -> llm_api_key."""
        try:
            import keyring

            stored = keyring.get_password("sago", "judge_api_key")
            if stored:
                return stored
        except Exception:
            pass
        return self.judge_api_key or self.llm_api_key

    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Temperature for LLM responses (0.0-2.0)",
    )
    llm_max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum tokens for LLM responses",
    )

    planning_dir: Path = Field(
        default=Path(".planning"),
        description="Directory for planning artifacts",
    )
    templates_dir: Path = Field(
        default=Path(__file__).parent.parent / "templates",
        description="Directory containing markdown templates",
    )

    enable_git_commits: bool = Field(
        default=True,
        description="Automatically create git commits for completed tasks",
    )
    enable_parallel_execution: bool = Field(
        default=False,
        description="Execute independent tasks in parallel (may cause file conflicts)",
    )
    max_concurrent_tasks: int = Field(
        default=5,
        gt=0,
        description="Maximum number of tasks to run concurrently when parallel execution is on",
    )
    task_timeout: int = Field(
        default=300,
        gt=0,
        description="Timeout in seconds for task execution",
    )
    verify_timeout: int = Field(
        default=30,
        gt=0,
        description="Timeout in seconds for verify commands",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )
    log_file: Path | None = Field(
        default=None,
        description="Optional log file path",
    )

    enable_compression: bool = Field(
        default=False,
        description="Enable context compression for LLM calls (opt-in)",
    )
    max_context_tokens: int = Field(
        default=100000,
        gt=0,
        description="Token threshold for when compression kicks in",
    )

    enable_tracing: bool = Field(
        default=False,
        description="Enable trace event logging for observability dashboard",
    )
    trace_file: Path | None = Field(
        default=None,
        description="Path to trace JSONL file (auto-set when enable_tracing is True)",
    )

    def model_post_init(self, __context: object) -> None:
        self.planning_dir.mkdir(parents=True, exist_ok=True)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
