import logging
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.utils.agent_context import load_agent_context
from sago.utils.planning import (
    extract_xml_from_response,
    format_validation_errors,
    sanitize_xml,
    save_plan,
    validate_plan_semantics,
    validate_xml_structure,
)
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.parser = MarkdownParser()
        self.project_manager = ProjectManager(self.config)

    def _build_system_prompt(self) -> str:
        return """You are an expert software architect and project planner.

Rules:
- Break work into atomic, independently executable tasks
- Each task must produce concrete file changes — no vague or aspirational steps
- Order tasks so that dependencies are satisfied (earlier tasks create what later tasks need)
- Verification commands must be real, runnable shell commands (pytest, python -c, etc.)
- Action descriptions must be detailed enough for a code-generation agent to implement without guessing
- Only plan what the requirements ask for — no extra features or speculative tasks
- Honor any repo-local agent context files (IMPORTANT.md, AGENTS.md, SKILLS.md, CLAUDE.md, .cursorrules) when present
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
        plan_xml = sanitize_xml(plan_xml)
        validate_xml_structure(plan_xml)

        validation = validate_plan_semantics(plan_xml, self.parser)
        if not validation.valid:
            self.logger.warning("Plan has validation errors, retrying with feedback")
            error_feedback = format_validation_errors(validation)
            plan_xml = await self._retry_with_feedback(plan_xml, error_feedback)
            plan_xml = sanitize_xml(plan_xml)
            validate_xml_structure(plan_xml)
            validation = validate_plan_semantics(plan_xml, self.parser)
            if not validation.valid:
                error_msgs = "; ".join(i.message for i in validation.errors)
                raise ValueError(f"Plan has validation errors after retry: {error_msgs}")

        if validation.warnings:
            for w in validation.warnings:
                self.logger.warning(f"Plan warning: {w.message}")

        plan_path = project_path / "PLAN.md"
        save_plan(plan_path, plan_xml, agent_name="PlannerAgent")

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=f"Plan generated successfully: {plan_path}",
            metadata={
                "plan_path": str(plan_path),
                "plan_length": len(plan_xml),
                "num_phases": plan_xml.count("<phase"),
                "num_tasks": plan_xml.count("<task"),
                "validation_warnings": len(validation.warnings),
            },
        )

    def _load_project_context(self, project_path: Path) -> dict[str, str]:
        context: dict[str, str] = {}

        for filename in ["PROJECT.md", "REQUIREMENTS.md", "STATE.md"]:
            file_path = project_path / filename
            if not file_path.exists():
                if filename != "STATE.md":
                    self.logger.warning(f"File not found: {filename}")
                    context[filename] = ""
                else:
                    self.logger.debug(f"Optional file not present: {filename}")
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                if filename != "STATE.md":
                    self.logger.warning(f"Could not load {filename}: {e}")
                    context[filename] = ""
                else:
                    self.logger.debug(f"Could not load optional {filename}: {e}")
                continue

            context[filename] = content
            self.logger.debug(f"Loaded {filename}: {len(content)} chars")
            tracer.emit(
                "file_read",
                "PlannerAgent",
                {
                    "path": filename,
                    "size_bytes": len(content.encode("utf-8")),
                    "content_preview": content[:2000],
                },
            )

        agent_context = load_agent_context(project_path)
        if agent_context.present:
            context["AGENT_CONTEXT"] = agent_context.to_prompt_block()
            for entry in agent_context.files:
                tracer.emit(
                    "file_read",
                    "PlannerAgent",
                    {
                        "path": entry.path,
                        "size_bytes": len(entry.content.encode("utf-8")),
                        "content_preview": entry.content[:2000],
                    },
                )
        for error in agent_context.errors:
            self.logger.warning(f"Could not load agent context file: {error}")

        from sago.utils.repo_map import generate_repo_map

        repo_map = generate_repo_map(project_path)
        if repo_map:
            context["REPO_MAP"] = repo_map
            self.logger.debug(f"Generated repo map: {len(repo_map)} chars")

        from sago.utils.environment import detect_environment, format_environment_context

        env = detect_environment()
        context["ENVIRONMENT"] = format_environment_context(env)

        return context

    def _build_plan_user_prompt(self, project_context: dict[str, str]) -> str:
        """Build the user prompt for plan generation."""
        context_str = "\n\n".join(
            [f"=== {name} ===\n{content}" for name, content in project_context.items() if content]
        )

        from sago.utils.environment import PYPROJECT_TEMPLATE, detect_environment

        env = detect_environment()
        pyproject_example = PYPROJECT_TEMPLATE.replace("{python_version}", env["python_version"])

        return f"""Based on the project context below, generate a detailed PLAN.md with atomic tasks.

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

Generate a complete, executable plan now:"""

    async def _generate_plan_xml(self, project_context: dict[str, str]) -> str:
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": self._build_plan_user_prompt(project_context),
            },
        ]

        response = await self._call_llm(messages)
        return extract_xml_from_response(response["content"])

    async def _retry_with_feedback(self, original_xml: str, error_feedback: str) -> str:
        """Retry plan generation with error feedback."""
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Your previous plan had validation errors. "
                    f"Fix them and output a corrected <phases> XML block.\n\n"
                    f"Previous plan:\n```xml\n{original_xml}\n```\n\n"
                    f"{error_feedback}\n\n"
                    f"Output the COMPLETE corrected <phases> XML block now:"
                ),
            },
        ]
        response = await self._call_llm(messages)
        return extract_xml_from_response(response["content"])
