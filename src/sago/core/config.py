from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: str = Field(
        default="openai",
        description="LLM provider (openai, anthropic, azure, etc.)",
    )
    llm_model: str = Field(
        default="gpt-4o",
        description="Model name to use for AI operations",
    )
    llm_api_key: str = Field(
        default="",
        description="API key for LLM provider",
    )
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

    hosts_file: Path | None = Field(
        default=None,
        description="Path to hosts file (auto-detected if None)",
    )
    blocked_domains: list[str] = Field(
        default_factory=list,
        description="List of domains to block by default",
    )

    focus_domains: list[str] = Field(
        default=[
            "youtube.com",
            "reddit.com",
            "twitter.com",
            "x.com",
            "tiktok.com",
            "instagram.com",
            "facebook.com",
        ],
        description="Domains to block during focus mode workflows",
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

    def get_hosts_file_path(self) -> Path:
        if self.hosts_file:
            return self.hosts_file

        import platform

        system = platform.system()
        if system == "Windows":
            return Path(r"C:\Windows\System32\drivers\etc\hosts")
        else:
            return Path("/etc/hosts")

    def model_post_init(self, __context: object) -> None:
        self.planning_dir.mkdir(parents=True, exist_ok=True)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
