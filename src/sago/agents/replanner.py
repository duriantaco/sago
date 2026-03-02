import logging
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import MarkdownParser
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class ReplannerAgent(BaseAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.parser = MarkdownParser()

    def _build_system_prompt(self) -> str:
        return """You are an expert software architect updating an existing project plan.

You are UPDATING an existing project plan, not creating one from scratch.

Rules for modifying the plan:
- Tasks marked DONE must be preserved exactly — same id, name, action, verify, done, depends_on
- Tasks marked FAILED can be modified or replaced
- PENDING tasks can be modified, reordered, added, or removed
- Keep task IDs stable where possible for STATE.md continuity
- If a completed task must be redone due to the change, add a NEW task with a new ID
- Output the COMPLETE <phases> XML block (not a diff)
- Each task must be ATOMIC (completable in one session)
- Each task must have: id, name, files, action, verify, done
- Tasks must be ordered by dependencies within each phase
- Do NOT use special XML characters (&, <, >) in text content — spell out "and" instead of &
- Verification commands must be real, runnable shell commands
- Action descriptions must be detailed enough for a code-generation agent to implement
- Only plan what the requirements ask for — no extra features or speculative tasks
"""

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Replan failed: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        project_path = Path(context.get("project_path", "."))
        feedback = context.get("feedback", "")
        review_context = context.get("review_context", "")
        extra_repo_map = context.get("repo_map", "")
        self.logger.info(f"Replanning for project: {project_path}")

        plan_path = project_path / "PLAN.md"
        if not plan_path.exists():
            raise ValueError("PLAN.md not found — run `sago plan` first")

        plan_content = plan_path.read_text(encoding="utf-8")
        current_xml = self._extract_xml(plan_content)

        phases = self.parser.parse_xml_tasks(plan_content)
        state_summary = self._build_state_summary(project_path, phases)

        project_context = self._load_project_context(
            project_path, skip_repo_map=bool(extra_repo_map)
        )

        if extra_repo_map:
            project_context["REPO_MAP"] = extra_repo_map

        updated_xml = await self._generate_replan_xml(
            current_xml,
            state_summary,
            feedback,
            project_context,
            review_context=review_context,
        )
        updated_xml = self._sanitize_xml(updated_xml)
        self._validate_plan(updated_xml)

        self._save_plan(plan_path, updated_xml)

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=f"Plan updated successfully: {plan_path}",
            metadata={
                "plan_path": str(plan_path),
                "plan_length": len(updated_xml),
                "num_phases": updated_xml.count("<phase"),
                "num_tasks": updated_xml.count("<task"),
            },
        )

    def _extract_xml(self, content: str) -> str:
        """Extract raw XML from PLAN.md content."""
        import re

        xml_match = re.search(r"```xml\s*(.*?)\s*```", content, re.DOTALL)
        if xml_match:
            return xml_match.group(1)

        raw_match = re.search(r"(<phases\b.*?</phases>)", content, re.DOTALL)
        if raw_match:
            return raw_match.group(1)

        raise ValueError("No XML task block found in PLAN.md")

    def _build_state_summary(self, project_path: Path, phases: list[Any]) -> str:
        """Build a summary of task states from STATE.md."""
        state_path = project_path / "STATE.md"
        if not state_path.exists():
            return "No STATE.md found — all tasks are PENDING."

        state_content = state_path.read_text(encoding="utf-8")
        task_states = self.parser.parse_state_tasks(state_content, phases)

        lines = []
        for ts in task_states:
            status_label = ts["status"].upper()
            lines.append(f"  {ts['id']}: {ts['name']} — {status_label}")

        done = sum(1 for ts in task_states if ts["status"] == "done")
        failed = sum(1 for ts in task_states if ts["status"] == "failed")
        pending = sum(1 for ts in task_states if ts["status"] == "pending")
        summary_header = f"Task states: {done} done, {failed} failed, {pending} pending\n"

        result = summary_header + "\n".join(lines)

        resume_point = self.parser.parse_resume_point(state_content)
        if resume_point is not None:
            result += "\n\nResume context:"
            result += f"\n  Last completed: {resume_point.last_completed}"
            result += f"\n  Next task: {resume_point.next_task}"
            if resume_point.failure_reason != "None":
                result += f"\n  Failure reason: {resume_point.failure_reason}"
            result += f"\n  Checkpoint: {resume_point.checkpoint}"

        return result

    def _load_project_context(
        self, project_path: Path, skip_repo_map: bool = False
    ) -> dict[str, str]:
        """Load project context files (PROJECT.md, REQUIREMENTS.md) and repo map."""
        context: dict[str, str] = {}
        for filename in ["PROJECT.md", "REQUIREMENTS.md"]:
            file_path = project_path / filename
            if file_path.exists():
                try:
                    context[filename] = file_path.read_text(encoding="utf-8")
                    tracer.emit(
                        "file_read",
                        "ReplannerAgent",
                        {
                            "path": filename,
                            "size_bytes": len(context[filename].encode("utf-8")),
                            "content_preview": context[filename][:2000],
                        },
                    )
                except Exception as e:
                    self.logger.warning(f"Could not load {filename}: {e}")

        if not skip_repo_map:
            from sago.utils.repo_map import generate_repo_map

            repo_map = generate_repo_map(project_path)
            if repo_map:
                context["REPO_MAP"] = repo_map
                self.logger.debug(f"Generated repo map: {len(repo_map)} chars")

        return context

    async def _generate_replan_xml(
        self,
        current_xml: str,
        state_summary: str,
        feedback: str,
        project_context: dict[str, str],
        review_context: str = "",
    ) -> str:
        context_str = "\n\n".join(
            f"=== {name} ===\n{content}" for name, content in project_context.items() if content
        )

        review_section = ""
        if review_context:
            review_section = f"""
Phase Review Feedback:
{review_context}

"""

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": f"""Update the project plan based on the feedback below.

Current Plan XML:
```xml
{current_xml}
```

Task Status:
{state_summary}
{review_section}User Feedback:
{feedback}

Project Context:
{context_str}

CRITICAL REQUIREMENTS:
1. Output the COMPLETE updated <phases> XML block
2. Preserve all DONE tasks exactly as they are (same id, name, action, verify, done, depends_on)
3. FAILED tasks can be modified or replaced
4. PENDING tasks can be modified, reordered, added, or removed
5. Use XML format with <phases>, <phase>, and <task> tags
6. Each task must have: id, name, files, action, verify, done
7. Do NOT use special XML characters (&, <, >) in text content — spell out "and" instead of &
8. Keep existing <dependencies> and <review> blocks, updating them only if the feedback requires it
9. If the review finds issues in DONE tasks, add NEW corrective tasks with new IDs — do not modify the original done tasks

Generate the complete updated plan now:""",
            },
        ]

        response = await self._call_llm(messages)

        content: str = response["content"]
        xml_start = content.find("<phases>")
        xml_end = content.find("</phases>") + len("</phases>")

        if xml_start == -1 or xml_end < len("</phases>"):
            raise ValueError("Replan response does not contain valid XML structure")

        return content[xml_start:xml_end]

    def _sanitize_xml(self, xml_str: str) -> str:
        """Fix common XML issues from LLM output."""
        import re as _re

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

        self.logger.info("Updated plan XML validated successfully")

    def _save_plan(self, plan_path: Path, plan_xml: str) -> None:
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

*Updated by sago ReplannerAgent*
"""

        plan_path.write_text(content, encoding="utf-8")
        self.logger.info(f"Updated plan saved to {plan_path}")
        tracer.emit(
            "file_write",
            "ReplannerAgent",
            {
                "path": str(plan_path.name),
                "size_bytes": len(content.encode("utf-8")),
                "content_preview": content[:2000],
            },
        )
