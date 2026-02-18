import logging
import re
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import Task

logger = logging.getLogger(__name__)


class SelfHealingAgent(BaseAgent):

    MAX_FIX_ATTEMPTS = 3

    _FIX_PROMPTS: dict[str, str] = {
        "import_error": (
            "The code has an import error. Fix by: adding missing imports, "
            "correcting module names, fixing circular imports, or using correct import paths."
        ),
        "syntax_error": (
            "The code has a syntax error. Fix by: checking all brackets are balanced, "
            "fixing indentation, adding missing colons, or correcting Python syntax."
        ),
        "name_error": (
            "The code references an undefined name. Fix by: defining variables before use, "
            "fixing typos, checking scope, or adding missing parameters."
        ),
        "type_error": (
            "The code has a type error. Fix by: converting types appropriately, "
            "checking function signatures, fixing argument counts, or using correct operators."
        ),
        "indentation_error": (
            "The code has incorrect indentation. Fix by: using consistent 4-space indentation, "
            "fixing indentation levels, or removing mixed tabs/spaces."
        ),
        "test_failure": (
            "The verification test failed. Fix by: reviewing test expectations, "
            "fixing logic errors, handling edge cases, or implementing missing features."
        ),
    }

    _DEFAULT_FIX_PROMPT = (
        "Analyze the error and fix the code. Read the error message carefully, "
        "identify the line causing the error, understand what the code is trying to do, "
        "fix the specific issue, and verify the fix makes sense."
    )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Self-healing error: {e}", exc_info=True)
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
                metadata={"task_id": context.get("task", {}).get("id", "unknown")},
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        task: Task = context["task"]
        error: str = context["error"]
        original_code: str = context.get("original_code", "")
        project_path = Path(context.get("project_path", "."))

        self.logger.info(f"Attempting to fix task {task.id}: {task.name}")
        self.logger.info(f"Error: {error[:200]}")

        error_type = self._classify_error(error)
        self.logger.info(f"Error type: {error_type}")

        fix_result = await self._generate_fix(
            task=task, original_code=original_code,
            error=error, error_type=error_type, project_path=project_path,
        )

        if fix_result["success"]:
            return self._create_result(
                status=AgentStatus.SUCCESS,
                output=f"Successfully fixed task {task.id}",
                metadata={
                    "task_id": task.id,
                    "error_type": error_type,
                    "fix_applied": fix_result["fix"],
                    "attempts": fix_result.get("attempts", 1),
                },
            )
        return self._create_result(
            status=AgentStatus.FAILURE,
            output=f"Could not fix task {task.id}",
            error=fix_result.get("error", "Unknown error"),
            metadata={
                "task_id": task.id,
                "error_type": error_type,
                "attempts": fix_result.get("attempts", 1),
            },
        )

    def _classify_error(self, error: str) -> str:

        error_lower = error.lower()

        if "import" in error_lower or "modulenotfounderror" in error_lower:
            return "import_error"

        if "syntaxerror" in error_lower or "invalid syntax" in error_lower:
            return "syntax_error"

        if "nameerror" in error_lower or "attributeerror" in error_lower:
            return "name_error"

        if "typeerror" in error_lower:
            return "type_error"

        if "indentationerror" in error_lower:
            return "indentation_error"

        if "assert" in error_lower or "failed" in error_lower:
            return "test_failure"

        return "unknown_error"

    def _build_fix_context(
        self,
        task: Task,
        original_code: str,
        error: str,
        error_type: str,
        project_path: Path,
    ) -> str:
        """Build context string for the fix LLM call."""
        parts = [
            "=== TASK ===",
            f"ID: {task.id}", f"Name: {task.name}", f"Action: {task.action}",
            "", "=== ORIGINAL CODE ===", original_code,
            "", "=== ERROR ===", f"Type: {error_type}", f"Message: {error}",
        ]

        for file_path_str in task.files:
            file_path = project_path / file_path_str
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    parts.append(f"\n=== CURRENT: {file_path_str} ===")
                    parts.append(content)
                except Exception:
                    pass

        return "\n".join(parts)

    def _build_fix_messages(self, context: str, error_type: str) -> list[dict[str, str]]:
        """Build LLM messages for the fix request."""
        fix_prompt = self._build_fix_prompt(error_type)
        return [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    "expert debugging agent that fixes code errors"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{context}\n\n{fix_prompt}\n\n"
                    "IMPORTANT:\n"
                    "1. Analyze the error carefully\n"
                    "2. Identify the root cause\n"
                    "3. Generate ONLY the corrected code\n"
                    "4. Ensure the fix addresses the specific error\n"
                    "5. Don't change unrelated code\n\n"
                    "Output format - use this exact format:\n\n"
                    "=== FILE: path/to/file.py ===\n"
                    "```python\n# Corrected code here\n```\n\n"
                    "Generate the fix now:"
                ),
            },
        ]

    async def _generate_fix(
        self,
        task: Task,
        original_code: str,
        error: str,
        error_type: str,
        project_path: Path,
    ) -> dict[str, Any]:

        context = self._build_fix_context(task, original_code, error, error_type, project_path)
        messages = self._build_fix_messages(context, error_type)

        try:
            response = await self._call_llm(messages)
            fix_code = self._parse_fix(response["content"])

            if not fix_code:
                return {"success": False, "error": "Could not parse fix from LLM response"}

            return {"success": True, "fix": fix_code, "attempts": 1}

        except Exception as e:
            self.logger.error(f"Failed to generate fix: {e}")
            return {"success": False, "error": str(e), "attempts": 1}

    def _build_fix_prompt(self, error_type: str) -> str:
        return self._FIX_PROMPTS.get(error_type, self._DEFAULT_FIX_PROMPT)

    def _parse_fix(self, content: str) -> dict[str, str]:
 
        fixes = {}
        file_pattern = r"===\s*FILE:\s*([^\s]+)\s*===\s*```(?:\w+)?\s*(.*?)\s*```"

        matches = re.finditer(file_pattern, content, re.DOTALL | re.MULTILINE)

        for match in matches:
            file_path = match.group(1).strip()
            file_content = match.group(2).strip()
            fixes[file_path] = file_content

        return fixes

    def should_attempt_fix(self, error: str, task: Task) -> bool:

        fixable_errors = [
            "import",
            "syntax",
            "name",
            "type",
            "indentation",
            "attribute",
        ]

        error_lower = error.lower()
        for err_type in fixable_errors:
            if err_type in error_lower:
                return True

        if len(error.strip()) < 20:
            return False

        if "failed" in error_lower or "assert" in error_lower:
            return True

        return False
