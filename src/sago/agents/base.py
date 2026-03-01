import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sago.core.config import Config
from sago.utils.compression import ContextManager
from sago.utils.llm import LLMClient
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class AgentStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    PENDING = "pending"


@dataclass
class AgentResult:
    status: AgentStatus
    output: str
    metadata: dict[str, Any]
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == AgentStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "output": self.output,
            "metadata": self.metadata,
            "error": self.error,
        }


class BaseAgent(ABC):
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
            tracer.emit(
                "compression",
                self.__class__.__name__,
                {
                    "original_tokens": result.original_tokens,
                    "compressed_tokens": result.compressed_tokens,
                    "savings_pct": round(result.percentage_saved, 1),
                },
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
        return f"""You are a {role}.

Rules:
- Generate complete, working code — never pseudocode, stubs, or TODO comments
- Match the existing project's style, naming conventions, and patterns
- Every file you output must be syntactically valid and immediately runnable
- Only output what was asked for — no extra files, no unsolicited refactoring
- If the task specifies a verification command, your output MUST pass it
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

    async def _call_llm(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        """Call LLM with retry logic (native async via litellm.acompletion).

        Args:
            messages: Message list for LLM
            **kwargs: Additional LLM parameters

        Returns:
            LLM response dictionary
        """
        agent_name = self.__class__.__name__
        try:
            self.logger.info(f"Calling LLM with {len(messages)} messages")
            start = time.monotonic()
            response = await self.llm.achat_completion(messages, **kwargs)
            duration_s = time.monotonic() - start
            usage = response.get("usage", {})
            self.logger.info(
                f"LLM response: prompt={usage.get('prompt_tokens', 0)}, "
                f"completion={usage.get('completion_tokens', 0)}, "
                f"total={usage.get('total_tokens', 0)} tokens"
            )
            prompt_preview = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    prompt_preview = (m.get("content") or "")[:3000]
                    break
            response_preview = (response.get("content") or "")[:5000]
            tracer.emit(
                "llm_call",
                agent_name,
                {
                    "model": self.config.llm_model,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "duration_s": round(duration_s, 3),
                    "prompt_preview": prompt_preview,
                    "response_preview": response_preview,
                },
                duration_ms=round(duration_s * 1000, 2),
            )
            return response
        except Exception as e:
            self.logger.error(f"LLM call failed: {e}")
            tracer.emit("error", agent_name, {"error_type": "llm_call", "message": str(e)})
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
