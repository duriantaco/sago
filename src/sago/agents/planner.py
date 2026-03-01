import logging
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.parser = MarkdownParser()
        self.project_manager = ProjectManager(self.config)

    def _build_system_prompt(self, role: str) -> str:
        return f"""You are a {role}.

Rules:
- Break work into atomic, independently executable tasks
- Each task must produce concrete file changes — no vague or aspirational steps
- Order tasks so that dependencies are satisfied (earlier tasks create what later tasks need)
- Verification commands must be real, runnable shell commands (pytest, python -c, etc.)
- Action descriptions must be detailed enough for a code-generation agent to implement without guessing
- Only plan what the requirements ask for — no extra features or speculative tasks
"""

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Plan generation failed: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        project_path = Path(context.get("project_path", "."))
        self.logger.info(f"Generating plan for project: {project_path}")

        project_context = self._load_project_context(project_path)
        plan_xml = await self._generate_plan_xml(project_context)
        plan_xml = self._sanitize_xml(plan_xml)
        self._validate_plan(plan_xml)

        plan_path = project_path / "PLAN.md"
        self._save_plan(plan_path, plan_xml, project_context)

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=f"Plan generated successfully: {plan_path}",
            metadata={
                "plan_path": str(plan_path),
                "plan_length": len(plan_xml),
                "num_phases": plan_xml.count("<phase"),
                "num_tasks": plan_xml.count("<task"),
            },
        )

    def _load_project_context(self, project_path: Path) -> dict[str, str]:
        context = {}

        required_files = ["PROJECT.md", "REQUIREMENTS.md"]
        optional_files = ["IMPORTANT.md", "STATE.md"]

        for filename in required_files:
            file_path = project_path / filename
            if file_path.exists():
                try:
                    context[filename] = file_path.read_text(encoding="utf-8")
                    self.logger.debug(f"Loaded {filename}: {len(context[filename])} chars")
                    tracer.emit(
                        "file_read",
                        "PlannerAgent",
                        {
                            "path": filename,
                            "size_bytes": len(context[filename].encode("utf-8")),
                            "content_preview": context[filename][:2000],
                        },
                    )
                except Exception as e:
                    self.logger.warning(f"Could not load {filename}: {e}")
                    context[filename] = ""
            else:
                self.logger.warning(f"File not found: {filename}")
                context[filename] = ""

        for filename in optional_files:
            file_path = project_path / filename
            if file_path.exists():
                try:
                    context[filename] = file_path.read_text(encoding="utf-8")
                    self.logger.debug(f"Loaded {filename}: {len(context[filename])} chars")
                    tracer.emit(
                        "file_read",
                        "PlannerAgent",
                        {
                            "path": filename,
                            "size_bytes": len(context[filename].encode("utf-8")),
                            "content_preview": context[filename][:2000],
                        },
                    )
                except Exception as e:
                    self.logger.debug(f"Could not load optional {filename}: {e}")
            else:
                self.logger.debug(f"Optional file not present: {filename}")

        from sago.utils.repo_map import generate_repo_map

        repo_map = generate_repo_map(project_path)
        if repo_map:
            context["REPO_MAP"] = repo_map
            self.logger.debug(f"Generated repo map: {len(repo_map)} chars")

        from sago.utils.environment import detect_environment, format_environment_context

        env = detect_environment()
        context["ENVIRONMENT"] = format_environment_context(env)

        return context

    async def _generate_plan_xml(self, project_context: dict[str, str]) -> str:
        context_str = "\n\n".join(
            [f"=== {name} ===\n{content}" for name, content in project_context.items() if content]
        )

        from sago.utils.environment import PYPROJECT_TEMPLATE, detect_environment

        env = detect_environment()
        pyproject_example = PYPROJECT_TEMPLATE.replace("{python_version}", env["python_version"])

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(
                    "expert software architect and project planner"
                ),
            },
            {
                "role": "user",
                "content": f"""Based on the project context below, generate a detailed PLAN.md with atomic tasks.

Project Context:
{context_str}

CRITICAL REQUIREMENTS:
1. Use XML format with <phases>, <phase>, and <task> tags
2. Include a <review> tag inside <phases> (before the first <phase>) with instructions for reviewing each phase's output
3. Each task must be ATOMIC (completable in one session)
4. Each task must have: id, name, files, action, verify, done
5. Tasks must be ordered by dependencies
6. Each phase should group related tasks
7. Action must be detailed enough for execution
8. Do NOT use special XML characters (&, <, >) in text content — spell out "and" instead of &
11. Use depends_on="id1,id2" attribute on <task> to declare dependencies on other tasks. \
Omit depends_on when a task depends on all prior tasks in its phase (the default). \
Use it when a task has NO dependencies, or depends on specific tasks only.
9. Include a <dependencies> block inside <phases> (before <review>) listing all third-party \
packages. Use <package> tags with version constraints:
     <dependencies>
       <package>flask>=2.0</package>
       <package>requests>=2.28</package>
     </dependencies>
   Only suggest packages available on PyPI that support the Python version shown in ENVIRONMENT. \
Do NOT include stdlib modules or dev-only tools.
10. When any task creates pyproject.toml, use PEP 621 format with setuptools:
{pyproject_example}
    NEVER use poetry ([tool.poetry]), flit, or hatch formats.

VERIFY COMMAND RULES (critical — broken verify = failed task):
- ONLY use: python -c "...", pytest, or simple file checks (test -f, ls)
- Verify must check that the FILES THIS TASK CREATES actually exist and are valid Python
- NEVER import third-party packages (tensorflow, torch, numpy, flask, etc.) in verify — they may not be installed
- NEVER start long-running processes (servers, daemons) in verify
- NEVER assume external tools (aws, docker, kubectl, etc.) are installed
- For Python files: use "python -c" to import the module and print a success message
- For config/data files: use "test -f path/to/file" or "python -c" to parse them
- Keep verify commands simple and fast (under 10 seconds)

Example Structure:
```xml
<phases>
    <dependencies>
        <package>flask>=2.0</package>
        <package>sqlalchemy>=2.0</package>
    </dependencies>

    <review>
        Review the completed phase. For every issue:
        - Describe the problem with file and line references
        - Assess severity (critical, warning, suggestion)
        - Provide concrete fix instructions
        Focus on: code quality, edge cases, DRY violations,
        security issues, and alignment with requirements.
    </review>

    <phase name="Phase 1: Foundation">
        <description>Set up project structure</description>

        <task id="1.1">
            <name>Initialize Python Project</name>
            <files>
                pyproject.toml
                src/__init__.py
            </files>
            <action>
                Create project structure with:
                - pyproject.toml with dependencies (PEP 621 format, setuptools backend)
                - src/__init__.py with version info
                - Modern Python 3.11+ setup
            </action>
            <verify>
                python -c "import sys; sys.path.insert(0, 'src'); import myproject; print('OK')"
            </verify>
            <done>Project imports successfully without errors</done>
        </task>

        <task id="1.2" depends_on="1.1">
            <name>Add Configuration</name>
            <files>src/config.py</files>
            <action>Create configuration module that reads from environment</action>
            <verify>python -c "from config import Config; print('OK')"</verify>
            <done>Config module loads correctly</done>
        </task>
    </phase>
</phases>
```

Generate a complete, executable plan now:""",
            },
        ]

        response = await self._call_llm(messages)

        content: str = response["content"]
        xml_start = content.find("<phases>")
        xml_end = content.find("</phases>") + len("</phases>")

        if xml_start == -1 or xml_end < len("</phases>"):
            raise ValueError("Generated plan does not contain valid XML structure")

        return content[xml_start:xml_end]

    def _sanitize_xml(self, xml_str: str) -> str:
        """Fix common XML issues from LLM output (bare &, unescaped chars in text)."""
        import re as _re

        # Replace bare & that aren't already entities (e.g. "TCP & HTTP" but not "&amp;")
        xml_str = _re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xml_str)
        return xml_str

    def _validate_plan(self, plan_xml: str) -> None:
        if "<phases>" not in plan_xml or "</phases>" not in plan_xml:
            raise ValueError("Plan missing <phases> tags")

        if "<phase" not in plan_xml:
            raise ValueError("Plan has no phases")

        if "<task" not in plan_xml:
            raise ValueError("Plan has no tasks")

        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(plan_xml)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML structure: {e}") from e

        self.logger.info("Plan XML validated successfully")

    def _save_plan(self, plan_path: Path, plan_xml: str, project_context: dict[str, str]) -> None:
        content = f"""# PLAN.md

> **CRITICAL COMPONENT:** This file uses a specific XML schema to force the AI into "Atomic Task" mode.

```xml
{plan_xml}
```

## Task Structure Schema

The `<phases>` block contains:
- **`<dependencies>`** (optional): Lists third-party packages needed by the project. Each package is a `<package>` element with optional version constraints (e.g. `flask>=2.0`).
- **`<review>`** (optional): Instructions for post-phase code review. If present, a review runs automatically after each phase completes and feedback carries forward to the next phase.

Each `<task>` has attributes:
- **id:** Unique identifier (phase.task format)
- **depends_on:** (optional) Comma-separated task IDs this task depends on. Omit to depend on all prior tasks in the phase.

Each `<task>` must contain child elements:
- **name:** Clear, actionable task name
- **files:** Specific files to create/modify
- **action:** Detailed implementation instructions
- **verify:** Command to verify task completion
- **done:** Acceptance criteria

## Execution Rules

1. **Follow task dependencies** - Check `depends_on` to determine task order. Tasks without `depends_on` depend on all prior tasks in their phase.
2. **Parallel between phases** - Independent phases can run concurrently
3. **Verify before proceeding** - Each task must pass verification
4. **Update STATE.md** - Log progress after each task
5. **Atomic commits** - One commit per completed task

---

*Generated by sago PlannerAgent*
"""

        plan_path.write_text(content, encoding="utf-8")
        self.logger.info(f"Plan saved to {plan_path}")
        tracer.emit(
            "file_write",
            "PlannerAgent",
            {
                "path": str(plan_path.name),
                "size_bytes": len(content.encode("utf-8")),
                "content_preview": content[:2000],
            },
        )
