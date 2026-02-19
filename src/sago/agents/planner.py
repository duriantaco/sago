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

        return context

    async def _generate_plan_xml(self, project_context: dict[str, str]) -> str:
        context_str = "\n\n".join(
            [f"=== {name} ===\n{content}" for name, content in project_context.items() if content]
        )

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
2. Each task must be ATOMIC (completable in one session)
3. Each task must have: id, name, files, action, verify, done
4. Tasks must be ordered by dependencies
5. Each phase should group related tasks
6. Verify commands must be executable (pytest, python -c, etc.)
7. Action must be detailed enough for execution

Example Structure:
```xml
<phases>
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
                - pyproject.toml with dependencies
                - src/__init__.py with version info
                - Modern Python 3.11+ setup
            </action>
            <verify>
                python -c "import sys; sys.path.insert(0, 'src'); import myproject; print('OK')"
            </verify>
            <done>Project imports successfully without errors</done>
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

Each `<task>` must contain:
- **id:** Unique identifier (phase.task format)
- **name:** Clear, actionable task name
- **files:** Specific files to create/modify
- **action:** Detailed implementation instructions
- **verify:** Command to verify task completion
- **done:** Acceptance criteria

## Execution Rules

1. **Sequential within phases** - Complete tasks in order within each phase
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
