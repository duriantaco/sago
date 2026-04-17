"""State manager backed by canonical JSON with STATE.md rendering."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sago.models.plan import Phase
from sago.models.state import (
    PhaseGateStatus,
    PhaseReview,
    ProjectState,
    ResumePoint,
    TaskState,
    TaskStatus,
)
from sago.persistence import PersistedProjectState, ProjectStateStore

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
    """Owns all project-state reads and writes for STATE.md and project_state.json."""

    def __init__(self, state_path: Path) -> None:
        self.path = state_path
        self.store = ProjectStateStore(state_path)

    @property
    def structured_state_path(self) -> Path:
        return self.store.persisted_path

    def exists(self) -> bool:
        return self.store.exists()

    def state_mtime(self) -> float:
        return self.store.state_mtime()

    def _load_state(self) -> PersistedProjectState:
        return self.store.load()

    def _save_state(self, state: PersistedProjectState) -> None:
        self.store.save(state)

    def _read(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        state = self._load_state()
        if self.path.exists():
            return self.path.read_text(encoding="utf-8")
        return state.render_markdown(self.path.parent.name)

    def task_status(self, task_id: str) -> TaskStatus:
        """Return the current status of a task."""
        state = self._load_state()
        record = state.task_record_map().get(task_id)
        return record.status if record is not None else TaskStatus.PENDING

    def get_task_states(self, plan_phases: list[Phase]) -> list[TaskState]:
        """Return task states aligned to the current plan."""
        state = self._load_state()
        return state.to_public_state(plan_phases).task_states

    def completed_task_ids(self) -> list[str]:
        """Return list of completed task IDs."""
        return self._load_state().completed_task_ids()

    def get_project_state(self, plan_phases: list[Phase]) -> ProjectState:
        """Return the public project-state view for CLI/status surfaces."""
        return self._load_state().to_public_state(plan_phases)

    def get_resume_point(self) -> ResumePoint | None:
        """Read and return the current resume point, or None."""
        return self._load_state().resume_point

    def has_phase_summary(self, phase_name: str) -> bool:
        state = self._load_state()
        return phase_name in state.merged_phase_reviews()

    def get_phase_review(self, phase_name: str) -> PhaseReview | None:
        return self._load_state().merged_phase_reviews().get(phase_name)

    def phase_gate_status(self, phase_name: str) -> PhaseGateStatus:
        review = self.get_phase_review(phase_name)
        if review is None:
            return PhaseGateStatus.PENDING_REVIEW
        return review.gate_status

    def validate(self) -> ValidationResult:
        """Validate rendered STATE.md format. Returns warnings for any issues found."""
        content = self._read()
        result = ValidationResult()

        if not content:
            return result

        for section in ("## Current Context", "## Resume Point", "## Completed Tasks"):
            if section not in content:
                result.warnings.append(f"Missing section: {section}")
                result.valid = False

        task_ids: list[str] = []
        for match in re.finditer(r"^\[.\]\s+(\d+\.\d+):", content, re.MULTILINE):
            task_id = match.group(1)
            if task_id in task_ids:
                result.warnings.append(f"Duplicate task entry: {task_id}")
                result.valid = False
            task_ids.append(task_id)

        return result

    def _check_phase_complete(
        self, phase_task_ids: list[str] | None, phase_name: str, status: TaskStatus
    ) -> CheckpointResult:
        """Check if all tasks in a phase are done and mark complete if so."""
        result = CheckpointResult()
        if phase_task_ids and phase_name and status in {TaskStatus.DONE, TaskStatus.SKIPPED}:
            terminal_statuses = {TaskStatus.DONE, TaskStatus.SKIPPED}
            all_terminal = all(
                self.task_status(task_id) in terminal_statuses for task_id in phase_task_ids
            )
            if all_terminal:
                self.mark_phase_complete(phase_name)
                result.phase_completed = True
                result.phase_name = phase_name
        return result

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
        """Record a task checkpoint — the primary state mutation."""
        state = self._load_state()
        state.upsert_task_record(
            task_id=task_id,
            task_name=task_name,
            status=status,
            note=notes,
        )

        if phase_name:
            state.active_phase = phase_name
            state.current_task = next_task or "None"

        failure_reason = notes if status == TaskStatus.FAILED else "None"
        checkpoint_tag = f"sago-checkpoint-{task_id}" if status == TaskStatus.DONE else "None"
        state.resume_point = ResumePoint(
            last_completed=f"{task_id}: {task_name}",
            next_task=next_task or "None",
            next_action=next_action or "None",
            failure_reason=failure_reason,
            checkpoint=checkpoint_tag,
        )

        if decisions:
            for decision in decisions:
                if decision not in state.decisions:
                    state.decisions.append(decision)

        self._save_state(state)
        return self._check_phase_complete(phase_task_ids, phase_name, status)

    def mark_phase_complete(self, phase_name: str) -> None:
        """Append a phase completion marker."""
        state = self._load_state()
        if phase_name in state.phase_completions:
            return
        state.phase_completions.append(phase_name)
        self._save_state(state)

    def append_phase_summary(self, phase_name: str, review_output: str) -> None:
        """Store a legacy phase summary as an approved review (skips if already present)."""
        state = self._load_state()
        if phase_name in state.merged_phase_reviews():
            return
        state.phase_summaries[phase_name] = review_output
        self._save_state(state)

    def record_phase_review(self, review: PhaseReview) -> None:
        """Persist a structured phase review."""
        state = self._load_state()
        state.phase_reviews[review.phase_name] = review
        state.phase_summaries.pop(review.phase_name, None)
        self._save_state(state)
