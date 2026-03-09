"""State manager — the single authority for STATE.md reads and writes.

All state mutations AND reads go through this module, guaranteeing format
consistency and a single source of truth.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sago.models.plan import Phase
from sago.models.state import ProjectState, ResumePoint, TaskState, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class CheckpointResult:
    """Result of a checkpoint operation."""

    phase_completed: bool = False
    phase_name: str = ""


@dataclass
class ValidationResult:
    """Result of STATE.md format validation."""

    valid: bool = True
    warnings: list[str] = field(default_factory=list)


class StateManager:
    """Owns all reads and writes to STATE.md."""

    def __init__(self, state_path: Path) -> None:
        self.path = state_path

    # ------------------------------------------------------------------
    # Read — public API
    # ------------------------------------------------------------------

    def _read(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return ""

    def task_status(self, task_id: str) -> TaskStatus:
        """Return the current status of a task from STATE.md."""
        content = self._read()
        if re.search(rf"\[✓\]\s+{re.escape(task_id)}:", content):
            return TaskStatus.DONE
        if re.search(rf"\[✗\]\s+{re.escape(task_id)}:", content):
            return TaskStatus.FAILED
        if re.search(rf"\[⊘\]\s+{re.escape(task_id)}:", content):
            return TaskStatus.SKIPPED
        return TaskStatus.PENDING

    def get_task_states(self, plan_phases: list[Phase]) -> list[TaskState]:
        """Parse STATE.md and return status for every task in the plan.

        Tasks not mentioned in STATE.md default to PENDING.
        """
        content = self._read()
        done_ids: set[str] = set()
        failed_ids: set[str] = set()
        skipped_ids: set[str] = set()

        for line in content.split("\n"):
            line = line.strip()
            m = re.match(r"\[✓\]\s+(\d+\.\d+):", line)
            if m:
                done_ids.add(m.group(1))
                continue
            m = re.match(r"\[✗\]\s+(\d+\.\d+):", line)
            if m:
                failed_ids.add(m.group(1))
                continue
            m = re.match(r"\[⊘\]\s+(\d+\.\d+):", line)
            if m:
                skipped_ids.add(m.group(1))

        results: list[TaskState] = []
        for phase in plan_phases:
            for task in phase.tasks:
                if task.id in done_ids:
                    status = TaskStatus.DONE
                elif task.id in failed_ids:
                    status = TaskStatus.FAILED
                elif task.id in skipped_ids:
                    status = TaskStatus.SKIPPED
                else:
                    status = TaskStatus.PENDING
                results.append(TaskState(task_id=task.id, status=status))
        return results

    def completed_task_ids(self) -> list[str]:
        """Return list of completed (done) task IDs from STATE.md."""
        content = self._read()
        return re.findall(r"\[✓\]\s+(\d+\.\d+):", content)

    def get_project_state(self, plan_phases: list[Phase]) -> ProjectState:
        """Parse STATE.md into a fully-populated ProjectState model.

        This is the canonical read method — replaces parse_state(),
        parse_state_file(), parse_state_tasks(), and _get_completed_task_ids().
        """
        content = self._read()

        # Parse Current Context
        active_phase = ""
        current_task = ""
        m = re.search(r"\*\s*\*\*Active Phase:\*\*\s*(.*)", content)
        if m:
            active_phase = m.group(1).strip()
        m = re.search(r"\*\s*\*\*Current Task:\*\*\s*(.*)", content)
        if m:
            current_task = m.group(1).strip()

        # Parse decisions
        decisions: list[str] = []
        dec_match = re.search(r"## Key Decisions\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if dec_match:
            for line in dec_match.group(1).split("\n"):
                line = line.strip()
                if line.startswith("*"):
                    decisions.append(line[1:].strip())

        # Parse blockers
        blockers: list[str] = []
        blk_match = re.search(
            r"### Known Blockers\s*\n(.*?)(?=\n## |\n### |\Z)", content, re.DOTALL
        )
        if blk_match:
            for line in blk_match.group(1).split("\n"):
                line = line.strip()
                if line.startswith("*"):
                    blockers.append(line[1:].strip())

        return ProjectState(
            active_phase=active_phase,
            current_task=current_task,
            task_states=self.get_task_states(plan_phases),
            decisions=decisions,
            blockers=blockers,
            resume_point=self.get_resume_point(),
        )

    def get_resume_point(self) -> ResumePoint | None:
        """Read and return the current resume point, or None."""
        content = self._read()
        match = re.search(r"## Resume Point\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not match:
            return None

        section = match.group(1)
        fields: dict[str, str] = {}
        for label in (
            "Last Completed",
            "Next Task",
            "Next Action",
            "Failure Reason",
            "Checkpoint",
        ):
            m = re.search(rf"\*\s*\*\*{re.escape(label)}:\*\*\s*(.*)", section)
            fields[label] = m.group(1).strip() if m else "None"

        if all(v == "None" for v in fields.values()):
            return None

        return ResumePoint(
            last_completed=fields["Last Completed"],
            next_task=fields["Next Task"],
            next_action=fields["Next Action"],
            failure_reason=fields["Failure Reason"],
            checkpoint=fields["Checkpoint"],
        )

    def validate(self) -> ValidationResult:
        """Validate STATE.md format. Returns warnings for any issues found."""
        content = self._read()
        result = ValidationResult()

        if not content:
            return result  # Empty/missing file is valid (not started)

        # Check required sections
        for section in ("## Current Context", "## Resume Point", "## Completed Tasks"):
            if section not in content:
                result.warnings.append(f"Missing section: {section}")
                result.valid = False

        # Check for duplicate task lines
        task_ids: list[str] = []
        for m in re.finditer(r"^\[.\]\s+(\d+\.\d+):", content, re.MULTILINE):
            tid = m.group(1)
            if tid in task_ids:
                result.warnings.append(f"Duplicate task entry: {tid}")
                result.valid = False
            task_ids.append(tid)

        return result

    # ------------------------------------------------------------------
    # Write — helpers
    # ------------------------------------------------------------------

    def _write(self, content: str) -> None:
        self.path.write_text(content, encoding="utf-8")

    def _ensure_completed_section(self, content: str) -> str:
        """Make sure the ## Completed Tasks section exists."""
        if "## Completed Tasks" not in content:
            content = content.rstrip("\n") + "\n\n## Completed Tasks\n"
        return content

    def _remove_existing_task_line(self, content: str, task_id: str) -> str:
        """Remove any existing checkpoint line for this task (allows re-checkpointing)."""
        pattern = rf"^\[.\]\s+{re.escape(task_id)}:.*\n?"
        return re.sub(pattern, "", content, flags=re.MULTILINE)

    def _update_resume_point(
        self,
        content: str,
        last_completed: str,
        next_task: str,
        next_action: str,
        failure_reason: str,
        checkpoint: str,
    ) -> str:
        """Replace the Resume Point section in content."""
        new_section = (
            "## Resume Point\n"
            "\n"
            f"* **Last Completed:** {last_completed}\n"
            f"* **Next Task:** {next_task}\n"
            f"* **Next Action:** {next_action}\n"
            f"* **Failure Reason:** {failure_reason}\n"
            f"* **Checkpoint:** {checkpoint}\n"
        )

        # Replace existing Resume Point section
        pattern = r"## Resume Point\s*\n(?:.*\n)*?(?=\n## |\Z)"
        if re.search(pattern, content):
            content = re.sub(pattern, new_section, content)
        else:
            # Insert before ## Completed Tasks if it exists
            if "## Completed Tasks" in content:
                content = content.replace(
                    "## Completed Tasks", new_section + "\n## Completed Tasks"
                )
            else:
                content = content.rstrip("\n") + "\n\n" + new_section
        return content

    def _update_current_context(self, content: str, active_phase: str, current_task: str) -> str:
        """Update the Current Context section."""
        content = re.sub(
            r"(\*\s*\*\*Active Phase:\*\*)\s*.*",
            f"\\1 {active_phase}",
            content,
        )
        content = re.sub(
            r"(\*\s*\*\*Current Task:\*\*)\s*.*",
            f"\\1 {current_task}",
            content,
        )
        return content

    # ------------------------------------------------------------------
    # Write — public API
    # ------------------------------------------------------------------

    def checkpoint(
        self,
        task_id: str,
        task_name: str,
        status: TaskStatus,
        notes: str = "",
        phase_name: str = "",
        next_task: str = "",
        next_action: str = "",
        decisions: list[str] | None = None,
        phase_task_ids: list[str] | None = None,
    ) -> CheckpointResult:
        """Record a task checkpoint — the primary state mutation.

        Args:
            task_id: Task identifier (e.g. "1.2")
            task_name: Human-readable task name
            status: done, failed, or skipped
            notes: Free-text notes about what happened
            phase_name: Current phase name (updates Current Context)
            next_task: ID + name of the next task to work on
            next_action: What to do next
            decisions: Key decisions made during this task
            phase_task_ids: All task IDs in the current phase (for auto phase detection)

        Returns:
            CheckpointResult indicating if phase was auto-completed
        """
        content = self._read()
        content = self._ensure_completed_section(content)
        content = self._remove_existing_task_line(content, task_id)

        # Build the checkpoint line
        icon = {"done": "✓", "failed": "✗", "skipped": "⊘"}[status.value]
        line = f"[{icon}] {task_id}: {task_name}"
        if notes:
            line += f" — {notes}"

        # Append to Completed Tasks section
        completed_idx = content.index("## Completed Tasks")
        rest = content[completed_idx + len("## Completed Tasks") :]
        next_section = re.search(r"\n## ", rest)
        if next_section:
            insert_pos = completed_idx + len("## Completed Tasks") + next_section.start()
            content = content[:insert_pos] + "\n" + line + content[insert_pos:]
        else:
            content = content.rstrip("\n") + "\n" + line + "\n"

        # Update Current Context
        if phase_name:
            current_task_display = next_task if next_task else "None"
            content = self._update_current_context(content, phase_name, current_task_display)

        # Update Resume Point
        failure_reason = notes if status == TaskStatus.FAILED else "None"
        checkpoint_tag = f"sago-checkpoint-{task_id}" if status == TaskStatus.DONE else ""
        content = self._update_resume_point(
            content,
            last_completed=f"{task_id}: {task_name}",
            next_task=next_task or "None",
            next_action=next_action or "None",
            failure_reason=failure_reason,
            checkpoint=checkpoint_tag or "None",
        )

        # Append decisions to a Key Decisions section
        if decisions:
            if "## Key Decisions" not in content:
                content = content.rstrip("\n") + "\n\n## Key Decisions\n"
            for decision in decisions:
                if decision not in content:
                    content = content.rstrip("\n") + f"\n* {decision}\n"

        self._write(content)

        # Auto phase detection
        result = CheckpointResult()
        if phase_task_ids and phase_name and status == TaskStatus.DONE:
            all_done = all(self.task_status(tid) == TaskStatus.DONE for tid in phase_task_ids)
            if all_done:
                self.mark_phase_complete(phase_name)
                result.phase_completed = True
                result.phase_name = phase_name

        return result

    def mark_phase_complete(self, phase_name: str) -> None:
        """Append a phase completion marker."""
        content = self._read()
        header = f"## Phase Complete: {phase_name}"
        if header in content:
            return
        content = content.rstrip("\n") + f"\n\n{header}\n"
        self._write(content)

    def append_phase_summary(self, phase_name: str, review_output: str) -> None:
        """Append a phase review summary (skips if already present)."""
        content = self._read()
        header = f"## Phase Summary: {phase_name}"
        if header in content:
            return
        block = f"\n{header}\n\n{review_output}\n"
        self._write(content + block)
