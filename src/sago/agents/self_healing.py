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
            "This is an import/module error. Common causes:\n"
            "- Missing package in dependencies (check pyproject.toml / requirements.txt)\n"
            "- Wrong module path (check project structure and __init__.py files)\n"
            "- Circular import (move imports inside functions or restructure)\n"
            "- Typo in module/package name\n"
            "Fix the import so the module resolves correctly."
        ),
        "syntax_error": (
            "This is a syntax error. The error message includes the exact line number "
            "and position. Go to that line and fix the syntax — common causes are: "
            "unmatched brackets/parentheses, missing colons after if/for/def/class, "
            "unterminated strings, or invalid Python 3.x syntax."
        ),
        "name_error": (
            "A variable or name is referenced before it's defined. Check:\n"
            "- Is the variable defined in the correct scope?\n"
            "- Is there a typo in the variable name?\n"
            "- Was the variable supposed to be passed as a parameter?\n"
            "- Is a required import missing?"
        ),
        "attribute_error": (
            "An object doesn't have the expected attribute/method. Check:\n"
            "- Is the object the correct type? (e.g., None when you expected a dict)\n"
            "- Is the method name spelled correctly?\n"
            "- Does the class actually define this attribute?\n"
            "- Was the wrong variable used?"
        ),
        "type_error": (
            "A type mismatch occurred. Check:\n"
            "- Are you passing the right number of arguments to a function?\n"
            "- Are you using the right types (str vs int, list vs dict)?\n"
            "- Is an operator being used with incompatible types?\n"
            "- Does a function return the expected type?"
        ),
        "value_error": (
            "An operation received an argument with the right type but wrong value. Check:\n"
            "- Are you unpacking the right number of values?\n"
            "- Is a string being converted to int/float with invalid content?\n"
            "- Are enum or literal values correct?"
        ),
        "key_error": (
            "A dictionary key or index doesn't exist. Check:\n"
            "- Is the key spelled correctly?\n"
            "- Should you use .get() with a default instead of direct access?\n"
            "- Is the data structure shaped as expected?"
        ),
        "file_not_found": (
            "A file or path doesn't exist. Check:\n"
            "- Is the path relative to the correct directory?\n"
            "- Does the file need to be created by a previous task?\n"
            "- Is the filename spelled correctly?"
        ),
        "indentation_error": (
            "The indentation is wrong. Use consistent 4-space indentation throughout. "
            "Check the specific line mentioned in the error — it likely has mixed "
            "tabs/spaces or is at the wrong indentation level."
        ),
        "test_failure": (
            "The verification test failed (assertion error or non-zero exit). This means "
            "the code runs but produces the wrong result. Read the assertion message "
            "carefully — it tells you the expected vs actual values. Fix the logic, "
            "not the test."
        ),
    }

    _DEFAULT_FIX_PROMPT = (
        "Analyze the error message and stack trace carefully. Identify the exact file "
        "and line where the error occurs, understand what the code is trying to do, "
        "and fix the specific issue. Do not change unrelated code."
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
        verify_stdout: str = context.get("verify_stdout", "")
        verify_stderr: str = context.get("verify_stderr", "")
        previous_attempts: list[str] = context.get("previous_attempts", [])

        self.logger.info(f"Attempting to fix task {task.id}: {task.name}")
        self.logger.info(f"Error: {error[:200]}")

        error_type = self._classify_error(error)
        self.logger.info(f"Error type: {error_type}")

        fix_result = await self._generate_fix(
            task=task, original_code=original_code,
            error=error, error_type=error_type, project_path=project_path,
            verify_stdout=verify_stdout, verify_stderr=verify_stderr,
            previous_attempts=previous_attempts,
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
        """Classify error using pattern matching on error messages."""
        error_lower = error.lower()

        if "indentationerror" in error_lower:
            return "indentation_error"

        if "syntaxerror" in error_lower or "invalid syntax" in error_lower:
            return "syntax_error"

        if "modulenotfounderror" in error_lower or "importerror" in error_lower:
            return "import_error"

        if "filenotfounderror" in error_lower or "no such file or directory" in error_lower:
            return "file_not_found"

        if "keyerror" in error_lower:
            return "key_error"

        if "valueerror" in error_lower:
            return "value_error"

        if "attributeerror" in error_lower:
            return "attribute_error"

        if "nameerror" in error_lower:
            return "name_error"

        if "typeerror" in error_lower:
            return "type_error"

        if re.search(r"(assert|failed|error.*test|FAILED\s+tests/)", error_lower):
            return "test_failure"

        return "unknown_error"

    def _extract_error_location(self, error: str) -> str:
        lines: list[str] = []

        tb_matches = re.finditer(
            r'File "([^"]+)",\s*line\s*(\d+)(?:,\s*in\s*(\S+))?', error
        )
        for m in tb_matches:
            filepath, lineno, func = m.group(1), m.group(2), m.group(3) or ""
            lines.append(f"  {filepath}:{lineno} in {func}")

        error_line_match = re.search(
            r"^(\w*Error\w*:\s*.+)$", error, re.MULTILINE
        )
        if error_line_match:
            lines.append(f"  Error: {error_line_match.group(1).strip()}")

        pytest_match = re.search(r"(FAILED\s+\S+)", error)
        if pytest_match:
            lines.append(f"  {pytest_match.group(1)}")

        assertion_matches = re.finditer(r"^E\s+(.+)$", error, re.MULTILINE)
        for m in assertion_matches:
            lines.append(f"  Assertion: {m.group(1).strip()}")

        if not lines:
            return ""
        return "Error location:\n" + "\n".join(lines)

    def _build_fix_context(
        self,
        task: Task,
        original_code: str,
        error: str,
        error_type: str,
        project_path: Path,
        verify_stdout: str = "",
        verify_stderr: str = "",
        previous_attempts: list[str] | None = None,
    ) -> str:
        parts = [
            "=== TASK ===",
            f"ID: {task.id}",
            f"Name: {task.name}",
            f"Action: {task.action}",
            f"Verification: {task.verify}",
        ]

        parts.append(f"\n=== ERROR ({error_type}) ===")
        location = self._extract_error_location(error)
        if location:
            parts.append(location)
        parts.append(f"\nFull error output:\n{error}")

        if verify_stdout and verify_stdout.strip():
            stdout_text = verify_stdout[:3000]
            parts.append(f"\n=== VERIFICATION STDOUT ===\n{stdout_text}")
        if verify_stderr and verify_stderr.strip():
            stderr_text = verify_stderr[:3000]
            parts.append(f"\n=== VERIFICATION STDERR ===\n{stderr_text}")

        if previous_attempts:
            parts.append("\n=== PREVIOUS FIX ATTEMPTS (these did NOT work, try something different) ===")
            for i, attempt in enumerate(previous_attempts, 1):
                parts.append(f"\nAttempt {i}:\n{attempt[:1500]}")

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

    def _build_fix_messages(
        self,
        context: str,
        error_type: str,
    ) -> list[dict[str, str]]:
        fix_prompt = self._build_fix_prompt(error_type)
        return [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    "senior debugger who fixes code errors quickly and precisely"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{context}\n\n"
                    f"DIAGNOSIS:\n{fix_prompt}\n\n"
                    "INSTRUCTIONS:\n"
                    "1. Read the error message and stack trace — identify the exact root cause\n"
                    "2. Fix ONLY the code that causes the error — do not rewrite unrelated code\n"
                    "3. Output the COMPLETE corrected file (not a diff)\n"
                    "4. The fix must make the verification command pass\n\n"
                    "OUTPUT FORMAT — use exactly this format for each file:\n\n"
                    "=== FILE: path/to/file.py ===\n"
                    "```python\n# Complete corrected file here\n```\n\n"
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
        verify_stdout: str = "",
        verify_stderr: str = "",
        previous_attempts: list[str] | None = None,
    ) -> dict[str, Any]:

        context = self._build_fix_context(
            task, original_code, error, error_type, project_path,
            verify_stdout, verify_stderr, previous_attempts,
        )
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
            "value",
            "key",
            "filenotfounderror",
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
