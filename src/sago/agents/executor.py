"""Executor agent for implementing tasks."""

import logging
import re
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import Task
from sago.core.project import ProjectManager

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """Agent that executes tasks by generating and applying code changes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize executor agent."""
        super().__init__(*args, **kwargs)
        self.project_manager = ProjectManager(self.config)

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Task execution failed: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
                metadata={"task_id": context.get("task", {}).get("id", "unknown")},
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        task: Task = context["task"]
        project_path = Path(context.get("project_path", "."))

        self.logger.info(f"Executing task {task.id}: {task.name}")

        task_context = await self._build_task_context(task, project_path)
        changes = await self._generate_changes(task, task_context)
        self._apply_changes(changes, project_path)

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=f"Task {task.id} executed successfully",
            metadata={
                "task_id": task.id,
                "files_modified": list(changes.keys()),
                "changes_count": len(changes),
            },
        )

    async def _build_task_context(self, task: Task, project_path: Path) -> str:
        """Build context for task execution.

        Args:
            task: Task to execute
            project_path: Project directory path

        Returns:
            Context string with relevant information
        """
        context_parts = []

        # Add task details
        context_parts.append("=== TASK ===")
        context_parts.append(f"ID: {task.id}")
        context_parts.append(f"Name: {task.name}")
        context_parts.append(f"Phase: {task.phase_name}")
        context_parts.append(f"\nAction:\n{task.action}")
        context_parts.append(f"\nFiles to modify:\n{chr(10).join(f'- {f}' for f in task.files)}")
        context_parts.append(f"\nVerification: {task.verify}")
        context_parts.append(f"Done criteria: {task.done}")

        # Add existing file contents if files exist
        for file_path_str in task.files:
            file_path = project_path / file_path_str
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    context_parts.append(f"\n=== EXISTING: {file_path_str} ===")
                    context_parts.append(content)
                except Exception as e:
                    self.logger.warning(f"Could not read {file_path}: {e}")

        # Add project context files
        for context_file in ["PROJECT.md", "REQUIREMENTS.md"]:
            file_path = project_path / context_file
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    # Limit context size
                    if len(content) > 2000:
                        content = content[:2000] + "\n... (truncated)"
                    context_parts.append(f"\n=== {context_file} ===")
                    context_parts.append(content)
                except Exception as e:
                    self.logger.warning(f"Could not read {context_file}: {e}")

        full_context = "\n".join(context_parts)
        return self._compress_context(full_context)

    async def _generate_changes(self, task: Task, context: str) -> dict[str, str]:
        """Generate code changes for task.

        Args:
            task: Task to execute
            context: Task context

        Returns:
            Dictionary mapping file paths to new content
        """
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    "expert software developer who writes clean, production-quality code"
                ),
            },
            {
                "role": "user",
                "content": f"""Generate code to complete this task:

{context}

CRITICAL REQUIREMENTS:
1. Generate complete, working code (not pseudocode or comments)
2. Follow best practices for the language/framework
3. Include proper error handling
4. Add type hints (if Python)
5. Write clean, readable code
6. Ensure code will pass the verification command
7. Only generate the specific files listed in the task

Output format:
For each file, use this format:

=== FILE: path/to/file.py ===
```python
# Complete file content here
```

Generate the code now:""",
            },
        ]

        response = await self._call_llm(messages)
        content = response["content"]

        # Parse generated code
        return self._parse_generated_code(content)

    def _parse_generated_code(self, content: str) -> dict[str, str]:
        """Parse generated code from LLM response.

        Args:
            content: LLM response content

        Returns:
            Dictionary mapping file paths to content
        """
        changes = {}

        # Pattern: === FILE: path/to/file.ext ===
        file_pattern = r"===\s*FILE:\s*([^\s]+)\s*===\s*```(?:\w+)?\s*(.*?)\s*```"

        matches = re.finditer(file_pattern, content, re.DOTALL | re.MULTILINE)

        for match in matches:
            file_path = match.group(1).strip()
            file_content = match.group(2).strip()

            changes[file_path] = file_content
            self.logger.info(f"Parsed changes for {file_path}: {len(file_content)} chars")

        if not changes:
            raise ValueError(
                "LLM response did not contain any files in the expected "
                "'=== FILE: path === ```code```' format. "
                f"Response length: {len(content)} chars"
            )

        return changes

    def _apply_changes(self, changes: dict[str, str], project_path: Path) -> None:
        """Apply code changes to files.

        Args:
            changes: Dictionary mapping file paths to new content
            project_path: Project directory path
        """
        for file_path_str, content in changes.items():
            file_path = project_path / file_path_str

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            file_path.write_text(content, encoding="utf-8")
            self.logger.info(f"Wrote {len(content)} chars to {file_path}")
