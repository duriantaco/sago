"""Base agent interface for all sago agents."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Any

from sago.core.config import Config
from sago.utils.compression import ContextManager
from sago.utils.llm import LLMClient

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    """Agent execution status."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    PENDING = "pending"


@dataclass
class AgentResult:
    """Result from agent execution."""

    status: AgentStatus
    output: str
    metadata: dict[str, Any]
    error: str | None = None

    @property
    def success(self) -> bool:
        """Check if agent execution was successful."""
        return self.status == AgentStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "output": self.output,
            "metadata": self.metadata,
            "error": self.error,
        }


class BaseAgent(ABC):
    """Abstract base class for all sago agents.

    All agents should inherit from this class and implement the execute() method.
    """

    def __init__(
        self,
        config: Config | None = None,
        llm_client: LLMClient | None = None,
        context_manager: ContextManager | None = None,
    ) -> None:
        """Initialize base agent.

        Args:
            config: Configuration instance
            llm_client: LLM client instance
            context_manager: Optional context compression manager
        """
        self.config = config or Config()
        self.llm = llm_client or LLMClient(
            model=self.config.llm_model,
            api_key=self.config.llm_api_key,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        self.context_manager = context_manager
        self.logger = logging.getLogger(self.__class__.__name__)

    def _compress_context(self, text: str) -> str:
        """Compress context text if a context manager is available.

        Args:
            text: Context text to potentially compress

        Returns:
            Original or compressed text
        """
        if self.context_manager is None:
            return text
        result = self.context_manager.auto_compress(text)
        if result.compressed_tokens < result.original_tokens:
            self.logger.info(
                f"Compressed context: {result.original_tokens} -> {result.compressed_tokens} "
                f"tokens ({result.percentage_saved:.1f}% saved)"
            )
        return result.compressed_text

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Execute the agent's task.

        Args:
            context: Context dictionary with task-specific information

        Returns:
            AgentResult with execution status and output
        """
        pass

    def _build_system_prompt(self, role: str) -> str:
        """Build system prompt for agent role.

        Args:
            role: Description of agent's role

        Returns:
            System prompt string
        """
        return f"""You are a {role} in the sago (Claude Code Control Protocol) system.

Your role is to {role}.

Guidelines:
- Be precise and accurate
- Follow best practices
- Generate production-quality output
- Explain your reasoning when appropriate
- Use the provided context effectively
- Format output as requested
"""

    def _build_prompt(self, task: str, context: str, output_format: str) -> list[dict[str, str]]:
        """Build messages for LLM.

        Args:
            task: Task description
            context: Context information
            output_format: Expected output format

        Returns:
            List of message dictionaries
        """
        return [
            {"role": "system", "content": self._build_system_prompt(self.__class__.__name__)},
            {
                "role": "user",
                "content": f"""Task: {task}

Context:
{context}

Please provide output in the following format:
{output_format}
""",
            },
        ]

    async def _call_llm(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """Call LLM with retry logic.

        Args:
            messages: Message list for LLM
            **kwargs: Additional LLM parameters

        Returns:
            LLM response dictionary
        """
        try:
            self.logger.info(f"Calling LLM with {len(messages)} messages")
            # Run sync LLM call in executor to avoid blocking the event loop
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, partial(self.llm.chat_completion, messages, **kwargs)
            )
            self.logger.info(f"LLM response: {response['usage']['total_tokens']} tokens")
            return response
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            raise

    def _create_result(
        self,
        status: AgentStatus,
        output: str,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AgentResult:
        """Create agent result.

        Args:
            status: Execution status
            output: Output string
            metadata: Optional metadata
            error: Optional error message

        Returns:
            AgentResult instance
        """
        return AgentResult(
            status=status,
            output=output,
            metadata=metadata or {},
            error=error,
        )
