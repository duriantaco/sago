import logging
import os
import re
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import Task
from sago.core.project import ProjectManager
from sago.utils.paths import safe_resolve
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)

_DEPENDENCY_FILES = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
]

_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".planning",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    ".tox",
    "dist",
    "build",
    "*.egg-info",
}


class ExecutorAgent(BaseAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.project_manager = ProjectManager(self.config)
        self._file_cache: dict[str, str] = {}
        self._tree_cache: str = ""

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
        context_parts = []

        context_parts.append("=== TASK ===")
        context_parts.append(f"ID: {task.id}")
        context_parts.append(f"Name: {task.name}")
        context_parts.append(f"Phase: {task.phase_name}")
        context_parts.append(f"\nAction:\n{task.action}")
        context_parts.append(
            f"\nFiles to create/modify:\n{chr(10).join(f'- {f}' for f in task.files)}"
        )
        context_parts.append(f"\nVerification command: {task.verify}")
        context_parts.append(f"Done criteria: {task.done}")

        tree = self._get_file_tree(project_path)
        if tree:
            context_parts.append(f"\n=== PROJECT STRUCTURE ===\n{tree}")

        dep_context = self._get_dependency_context(project_path)
        if dep_context:
            context_parts.append(dep_context)

        for file_path_str in task.files:
            self._read_file_into_context(
                project_path / file_path_str,
                file_path_str,
                context_parts,
                prefix="EXISTING: ",
            )

        for context_file in ["PROJECT.md", "REQUIREMENTS.md", "IMPORTANT.md"]:
            self._read_file_into_context(
                project_path / context_file,
                context_file,
                context_parts,
                truncate=4000,
            )

        full_context = "\n".join(context_parts)
        return self._compress_context(full_context)

    def _read_file_into_context(
        self,
        file_path: Path,
        display_name: str,
        context_parts: list[str],
        prefix: str = "",
        truncate: int = 0,
    ) -> None:
        if not file_path.exists():
            return
        try:
            cache_key = str(file_path)
            if cache_key in self._file_cache:
                content = self._file_cache[cache_key]
            else:
                content = file_path.read_text(encoding="utf-8")
                self._file_cache[cache_key] = content
            if truncate and len(content) > truncate:
                content = content[:truncate] + "\n... (truncated)"
            context_parts.append(f"\n=== {prefix}{display_name} ===\n{content}")
            tracer.emit(
                "file_read",
                "ExecutorAgent",
                {
                    "path": display_name,
                    "size_bytes": len(content.encode("utf-8")),
                    "content_preview": content[:2000],
                },
            )
        except (OSError, UnicodeDecodeError):
            self.logger.debug(f"Could not read {display_name}")

    def _walk_project_files(self, project_path: Path, max_lines: int) -> list[str]:
        lines: list[str] = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [
                d for d in sorted(dirs) if d not in _SKIP_DIRS and not d.endswith(".egg-info")
            ]
            rel = Path(root).relative_to(project_path)
            depth = len(rel.parts)
            indent = "  " * depth
            if rel != Path("."):
                lines.append(f"{indent}{rel.name}/")
            for f in sorted(files):
                if f.startswith(".") and f not in (".env.example", ".gitignore"):
                    continue
                lines.append(f"{indent}  {f}")
            if len(lines) >= max_lines:
                lines.append("  ... (truncated)")
                break
        return lines

    def _get_file_tree(self, project_path: Path, max_lines: int = 60) -> str:
        if self._tree_cache:
            return self._tree_cache
        try:
            lines = self._walk_project_files(project_path, max_lines)
        except Exception as e:
            self.logger.debug(f"Could not build file tree: {e}")
            return ""
        self._tree_cache = "\n".join(lines)
        return self._tree_cache

    def _get_dependency_context(self, project_path: Path) -> str:
        parts: list[str] = []
        for filename in _DEPENDENCY_FILES:
            file_path = project_path / filename
            if file_path.exists():
                try:
                    cache_key = str(file_path)
                    if cache_key in self._file_cache:
                        content = self._file_cache[cache_key]
                    else:
                        content = file_path.read_text(encoding="utf-8")
                        self._file_cache[cache_key] = content
                    if len(content) > 3000:
                        content = content[:3000] + "\n... (truncated)"
                    parts.append(f"\n=== {filename} ===\n{content}")
                    tracer.emit(
                        "file_read",
                        "ExecutorAgent",
                        {
                            "path": filename,
                            "size_bytes": len(content.encode("utf-8")),
                            "content_preview": content[:2000],
                        },
                    )
                except (OSError, UnicodeDecodeError):
                    pass
        return "\n".join(parts)

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
                    "senior software engineer implementing a task from a project plan"
                ),
            },
            {
                "role": "user",
                "content": f"""Implement the following task. The context includes the project structure, \
dependencies, existing files, and the project spec.

{context}

REQUIREMENTS:
1. Output COMPLETE file contents — every import, every function, every line. No placeholders.
2. Match the project's existing style, naming, and patterns (see EXISTING files and dependencies).
3. Your code MUST pass the verification command shown above.
4. Only generate the files listed in "Files to create/modify" — nothing else.
5. If modifying an existing file, include the FULL file contents (not a diff).

OUTPUT FORMAT — use exactly this format for each file:

=== FILE: path/to/file.ext ===
```language
complete file contents here
```

Generate the code now:""",
            },
        ]

        response = await self._call_llm(messages)
        content = response["content"]

        return self._parse_generated_code(content)

    def _parse_generated_code(self, content: str) -> dict[str, str]:
        changes = {}

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
        for file_path_str, content in changes.items():
            file_path = safe_resolve(project_path, file_path_str)

            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_path.write_text(content, encoding="utf-8")
            self.logger.info(f"Wrote {len(content)} chars to {file_path}")
            tracer.emit(
                "file_write",
                "ExecutorAgent",
                {
                    "path": file_path_str,
                    "size_bytes": len(content.encode("utf-8")),
                    "content_preview": content[:2000],
                },
            )
