import logging
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import MarkdownParser
from sago.models.execution import ExecutionHistory
from sago.models.state import TaskStatus
from sago.state import StateManager
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
- Honor any repo-local agent context files (IMPORTANT.md, AGENTS.md, SKILLS.md, CLAUDE.md, .cursorrules) when present
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
        execution_history: ExecutionHistory | None = context.get("execution_history")
        self.logger.info(f"Replanning for project: {project_path}")

        plan_path = project_path / "PLAN.md"
        if not plan_path.exists():
            raise ValueError("PLAN.md not found — run `sago plan` first")

        plan_content = plan_path.read_text(encoding="utf-8")
        current_xml = self._extract_xml(plan_content)

        phases = self.parser.parse_xml_tasks(plan_content)
        state_summary = self._build_state_summary(project_path, phases)

        execution_summary = self._build_execution_summary(execution_history)

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
            execution_summary=execution_summary,
        )
        updated_xml = sanitize_xml(updated_xml)
        validate_xml_structure(updated_xml)

        validation = validate_plan_semantics(updated_xml, self.parser)
        if not validation.valid:
            self.logger.warning("Replan has validation errors, retrying with feedback")
            error_feedback = format_validation_errors(validation)
            updated_xml = await self._retry_with_feedback(current_xml, error_feedback)
            updated_xml = sanitize_xml(updated_xml)
            validate_xml_structure(updated_xml)
            validation = validate_plan_semantics(updated_xml, self.parser)
            if not validation.valid:
                error_msgs = "; ".join(i.message for i in validation.errors)
                raise ValueError(f"Replan has validation errors after retry: {error_msgs}")

        if validation.warnings:
            for w in validation.warnings:
                self.logger.warning(f"Replan warning: {w.message}")

        save_plan(plan_path, updated_xml, agent_name="ReplannerAgent")

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=f"Plan updated successfully: {plan_path}",
            metadata={
                "plan_path": str(plan_path),
                "plan_length": len(updated_xml),
                "num_phases": updated_xml.count("<phase"),
                "num_tasks": updated_xml.count("<task"),
                "validation_warnings": len(validation.warnings),
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
        state_mgr = StateManager(state_path)

        if not state_path.exists():
            return "No STATE.md found — all tasks are PENDING."

        task_states = state_mgr.get_task_states(phases)

        # Build task-name lookup from phases
        task_names: dict[str, str] = {}
        for phase in phases:
            for task in phase.tasks:
                task_names[task.id] = task.name

        lines = []
        for ts in task_states:
            status_label = ts.status.value.upper()
            name = task_names.get(ts.task_id, ts.task_id)
            lines.append(f"  {ts.task_id}: {name} — {status_label}")

        done = sum(1 for ts in task_states if ts.status == TaskStatus.DONE)
        failed = sum(1 for ts in task_states if ts.status == TaskStatus.FAILED)
        pending = sum(1 for ts in task_states if ts.status == TaskStatus.PENDING)
        summary_header = f"Task states: {done} done, {failed} failed, {pending} pending\n"

        result = summary_header + "\n".join(lines)

        resume_point = state_mgr.get_resume_point()
        if resume_point is not None:
            result += "\n\nResume context:"
            result += f"\n  Last completed: {resume_point.last_completed}"
            result += f"\n  Next task: {resume_point.next_task}"
            if resume_point.failure_reason != "None":
                result += f"\n  Failure reason: {resume_point.failure_reason}"
            result += f"\n  Checkpoint: {resume_point.checkpoint}"

        return result

    def _build_execution_summary(self, execution_history: ExecutionHistory | None) -> str:
        """Build a structured summary of execution history for replan context."""
        if execution_history is None or not execution_history.records:
            return ""

        lines = ["Execution History:"]
        # Group by task
        tasks_seen: dict[str, list[Any]] = {}
        for record in execution_history.records:
            tasks_seen.setdefault(record.task_id, []).append(record)

        for task_id, records in tasks_seen.items():
            attempts = len(records)
            last = records[-1]
            vr = last.verifier_result
            status = "PASSED" if vr and vr.exit_code == 0 else "FAILED"
            lines.append(f"  Task {task_id}: {status} ({attempts} attempt(s))")
            if vr and vr.exit_code != 0:
                if vr.failure_category:
                    lines.append(f"    Category: {vr.failure_category}")
                if vr.stderr:
                    snippet = vr.stderr.strip()[:200]
                    lines.append(f"    stderr: {snippet}")

        return "\n".join(lines)

    def _load_project_context(
        self, project_path: Path, skip_repo_map: bool = False
    ) -> dict[str, str]:
        """Load project context files, agent context, and optionally repo map."""
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

        agent_context = load_agent_context(project_path)
        if agent_context.present:
            context["AGENT_CONTEXT"] = agent_context.to_prompt_block()
            for entry in agent_context.files:
                tracer.emit(
                    "file_read",
                    "ReplannerAgent",
                    {
                        "path": entry.path,
                        "size_bytes": len(entry.content.encode("utf-8")),
                        "content_preview": entry.content[:2000],
                    },
                )
        for error in agent_context.errors:
            self.logger.warning(f"Could not load agent context file: {error}")

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
        execution_summary: str = "",
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

        execution_section = ""
        if execution_summary:
            execution_section = f"""
{execution_summary}

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
{review_section}{execution_section}User Feedback:
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
        return extract_xml_from_response(response["content"])

    async def _retry_with_feedback(
        self,
        current_xml: str,
        error_feedback: str,
    ) -> str:
        """Retry replan with error feedback."""
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Your previous replan had validation errors. "
                    f"Fix them and output a corrected <phases> XML block.\n\n"
                    f"Previous plan:\n```xml\n{current_xml}\n```\n\n"
                    f"{error_feedback}\n\n"
                    f"Output the COMPLETE corrected <phases> XML block now:"
                ),
            },
        ]
        response = await self._call_llm(messages)
        return extract_xml_from_response(response["content"])
