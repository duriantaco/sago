import logging
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.models import Phase
from sago.utils.paths import safe_resolve
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Reviews completed phase output and produces feedback for subsequent phases."""

    def _build_system_prompt(self) -> str:
        return """You are a senior code reviewer auditing completed work from a project phase.

Rules:
- Generate complete, working code — never pseudocode, stubs, or TODO comments
- Match the existing project's style, naming conventions, and patterns
- Every file you output must be syntactically valid and immediately runnable
- Only output what was asked for — no extra files, no unsolicited refactoring
- If the task specifies a verification command, your output MUST pass it
"""

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Review failed: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
                metadata={
                    "phase_name": context.get(
                        "phase", Phase(name="", description="", tasks=[])
                    ).name
                },
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        phase: Phase = context["phase"]
        project_path = Path(context.get("project_path", "."))
        review_prompt: str = context["review_prompt"]

        self.logger.info(f"Reviewing phase: {phase.name}")

        review_context = self._build_review_context(phase, project_path)
        messages = self._build_review_messages(review_prompt, review_context)

        response = await self._call_llm(messages)
        review_output: str = response["content"]

        tracer.emit(
            "phase_review",
            "ReviewerAgent",
            {
                "phase_name": phase.name,
                "review_length": len(review_output),
                "review_preview": review_output[:2000],
            },
        )

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=review_output,
            metadata={
                "phase_name": phase.name,
                "review_length": len(review_output),
            },
        )

    def _read_file_truncated(
        self, path: Path, label: str, max_chars: int = 8000
    ) -> str | None:
        """Read a file and return its content truncated to max_chars, or None on failure."""
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated)"
            return content
        except (OSError, UnicodeDecodeError) as e:
            self.logger.debug(f"Could not read {label}: {e}")
            return None

    def _build_review_context(self, phase: Phase, project_path: Path) -> str:
        parts: list[str] = []

        parts.append(f"=== PHASE: {phase.name} ===")
        if phase.description:
            parts.append(f"Description: {phase.description}")

        parts.append("\n=== COMPLETED TASKS ===")
        for task in phase.tasks:
            parts.append(f"\nTask {task.id}: {task.name}")
            parts.append(f"  Action: {task.action}")
            parts.append(f"  Files: {', '.join(task.files)}")

        parts.append("\n=== GENERATED FILES ===")
        for task in phase.tasks:
            for file_path_str in task.files:
                file_path = safe_resolve(project_path, file_path_str)
                content = self._read_file_truncated(file_path, file_path_str)
                if content is not None:
                    parts.append(f"\n--- {file_path_str} ---\n{content}")
                elif file_path.exists():
                    parts.append(f"\n--- {file_path_str} --- (could not read)")

        for context_file in ["PROJECT.md", "REQUIREMENTS.md"]:
            ctx_path = project_path / context_file
            content = self._read_file_truncated(ctx_path, context_file, max_chars=4000)
            if content is not None:
                parts.append(f"\n=== {context_file} ===\n{content}")

        return "\n".join(parts)

    def _build_review_messages(
        self, review_prompt: str, review_context: str
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": f"""Review the completed phase using the instructions below.

=== REVIEW INSTRUCTIONS ===
{review_prompt}

{review_context}

Provide your review now. Be specific with file names and line references.
Format issues as:
- [CRITICAL] / [WARNING] / [SUGGESTION] description (file:line if applicable)""",
            },
        ]
