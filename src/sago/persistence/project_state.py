"""Canonical JSON-backed project state with STATE.md rendering."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from sago.models.plan import Phase
from sago.models.state import (
    PhaseReview,
    ProjectState,
    ResumePoint,
    ReviewFinding,
    ReviewSeverity,
    TaskState,
    TaskStatus,
)

_ICON_BY_STATUS = {
    TaskStatus.DONE: "✓",
    TaskStatus.FAILED: "✗",
    TaskStatus.SKIPPED: "⊘",
}
_STATUS_BY_ICON = {icon: status for status, icon in _ICON_BY_STATUS.items()}


class PersistedTaskRecord(BaseModel):
    """Canonical per-task record stored in project_state.json."""

    task_id: str
    task_name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    note: str = ""


class PersistedProjectState(BaseModel):
    """Canonical project state stored under .planning/runtime."""

    version: int = 1
    title: str = "State"
    active_phase: str = "Not started"
    current_task: str = "None"
    task_records: list[PersistedTaskRecord] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    resume_point: ResumePoint | None = None
    phase_completions: list[str] = Field(default_factory=list)
    phase_summaries: dict[str, str] = Field(default_factory=dict)
    phase_reviews: dict[str, PhaseReview] = Field(default_factory=dict)

    def task_record_map(self) -> dict[str, PersistedTaskRecord]:
        return {record.task_id: record for record in self.task_records}

    def upsert_task_record(
        self,
        task_id: str,
        task_name: str,
        status: TaskStatus,
        note: str = "",
    ) -> None:
        """Insert or replace a task record while preserving record order."""
        for idx, record in enumerate(self.task_records):
            if record.task_id == task_id:
                self.task_records[idx] = PersistedTaskRecord(
                    task_id=task_id,
                    task_name=task_name,
                    status=status,
                    note=note,
                )
                return
        self.task_records.append(
            PersistedTaskRecord(
                task_id=task_id,
                task_name=task_name,
                status=status,
                note=note,
            )
        )

    def completed_task_ids(self) -> list[str]:
        return [record.task_id for record in self.task_records if record.status == TaskStatus.DONE]

    def merged_phase_reviews(self) -> dict[str, PhaseReview]:
        reviews = dict(self.phase_reviews)
        for phase_name, summary in self.phase_summaries.items():
            reviews.setdefault(phase_name, PhaseReview.from_legacy_summary(phase_name, summary))
        return reviews

    def to_public_state(self, plan_phases: list[Phase]) -> ProjectState:
        """ProjectState view used by current CLI/status APIs."""
        record_map = self.task_record_map()
        plan_task_ids = {task.id for phase in plan_phases for task in phase.tasks}
        task_states = [
            TaskState(
                task_id=task.id,
                status=record_map.get(task.id, PersistedTaskRecord(task_id=task.id)).status,
                note="",
            )
            for phase in plan_phases
            for task in phase.tasks
        ]
        task_states.extend(
            TaskState(
                task_id=record.task_id,
                status=record.status,
                note=record.note,
            )
            for record in self.task_records
            if record.task_id not in plan_task_ids
        )
        return ProjectState(
            active_phase=self.active_phase,
            current_task=self.current_task,
            task_states=task_states,
            decisions=list(self.decisions),
            blockers=list(self.blockers),
            resume_point=self.resume_point,
            phase_reviews=self.merged_phase_reviews(),
        )

    def render_markdown(self, project_name: str) -> str:
        """Render the human-readable STATE.md view from canonical JSON state."""
        title = self.title or f"{project_name} State"
        lines = [
            f"# {title}",
            "",
            "## Current Context",
            "",
            f"* **Active Phase:** {self.active_phase or 'Not started'}",
            f"* **Current Task:** {self.current_task or 'None'}",
            "",
            "## Resume Point",
            "",
        ]

        if self.resume_point is None:
            lines.extend(
                [
                    "* **Last Completed:** None",
                    "* **Next Task:** None",
                    "* **Next Action:** None",
                    "* **Failure Reason:** None",
                    "* **Checkpoint:** None",
                ]
            )
        else:
            lines.extend(
                [
                    f"* **Last Completed:** {self.resume_point.last_completed}",
                    f"* **Next Task:** {self.resume_point.next_task}",
                    f"* **Next Action:** {self.resume_point.next_action}",
                    f"* **Failure Reason:** {self.resume_point.failure_reason}",
                    f"* **Checkpoint:** {self.resume_point.checkpoint}",
                ]
            )

        lines.extend(["", "## Completed Tasks"])
        for record in self.task_records:
            if record.status == TaskStatus.PENDING:
                continue
            line = (
                f"[{_ICON_BY_STATUS[record.status]}] "
                f"{record.task_id}: {record.task_name or record.task_id}"
            )
            if record.note:
                line += f" — {record.note}"
            lines.append(line)

        if self.decisions:
            lines.extend(["", "## Key Decisions", ""])
            lines.extend(f"* {decision}" for decision in self.decisions)

        if self.blockers:
            lines.extend(["", "### Known Blockers", ""])
            lines.extend(f"* {blocker}" for blocker in self.blockers)

        for phase_name in self.phase_completions:
            lines.extend(["", f"## Phase Complete: {phase_name}"])

        for phase_name, review in self.merged_phase_reviews().items():
            lines.extend(["", f"## Phase Review: {phase_name}", ""])
            lines.append(review.to_markdown())

        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def from_markdown(cls, content: str, project_name: str) -> PersistedProjectState:
        """Parse legacy STATE.md content into canonical JSON-backed state."""
        stripped = content.strip()
        if not stripped:
            return cls(title=f"{project_name} State")

        title_match = re.search(r"^#\s+(.*)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else f"{project_name} State"

        active_phase = _match_line(content, r"\*\s*\*\*Active Phase:\*\*\s*(.*)") or "Not started"
        current_task = _match_line(content, r"\*\s*\*\*Current Task:\*\*\s*(.*)") or "None"

        task_records: list[PersistedTaskRecord] = []
        for match in re.finditer(
            r"^\[([✓✗⊘])\]\s+(\d+\.\d+):\s*(.*?)(?:\s+—\s+(.*))?$",
            content,
            re.MULTILINE,
        ):
            icon, task_id, task_name, note = match.groups()
            task_records.append(
                PersistedTaskRecord(
                    task_id=task_id,
                    task_name=task_name.strip(),
                    status=_STATUS_BY_ICON[icon],
                    note=(note or "").strip(),
                )
            )

        decisions = _parse_bullet_section(content, r"## Key Decisions\s*\n(.*?)(?=\n## |\Z)")
        blockers = _parse_bullet_section(
            content,
            r"### Known Blockers\s*\n(.*?)(?=\n## |\n### |\Z)",
        )
        resume_point = _parse_resume_point(content)
        phase_completions = [
            match.group(1).strip()
            for match in re.finditer(r"^## Phase Complete:\s*(.+)$", content, re.MULTILINE)
        ]
        phase_summaries = _parse_phase_summaries(content)
        phase_reviews = _parse_phase_reviews(content)

        return cls(
            title=title,
            active_phase=active_phase,
            current_task=current_task,
            task_records=task_records,
            decisions=decisions,
            blockers=blockers,
            resume_point=resume_point,
            phase_completions=phase_completions,
            phase_summaries=phase_summaries,
            phase_reviews=phase_reviews,
        )


class ProjectStateStore:
    """Load and save canonical project state under .planning/runtime."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.project_root = state_path.parent
        self.runtime_dir = self.project_root / ".planning" / "runtime"
        self.persisted_path = self.runtime_dir / "project_state.json"

    def exists(self) -> bool:
        return self.persisted_path.exists() or self.state_path.exists()

    def state_mtime(self) -> float:
        mtimes: list[float] = []
        for path in (self.state_path, self.persisted_path):
            try:
                mtimes.append(path.stat().st_mtime)
            except OSError:
                continue
        return max(mtimes, default=0.0)

    def load(self) -> PersistedProjectState:
        """Load canonical state, migrating legacy markdown when needed."""
        if self.persisted_path.exists():
            if self.state_path.exists():
                try:
                    if self.state_path.stat().st_mtime > self.persisted_path.stat().st_mtime:
                        state = PersistedProjectState.from_markdown(
                            self.state_path.read_text(encoding="utf-8"),
                            self.project_root.name,
                        )
                        self.save(state)
                        return state
                except OSError:
                    pass
            state = PersistedProjectState.model_validate_json(
                self.persisted_path.read_text(encoding="utf-8")
            )
            if not self.state_path.exists():
                self._write_markdown(state)
            return state

        if self.state_path.exists():
            state = PersistedProjectState.from_markdown(
                self.state_path.read_text(encoding="utf-8"),
                self.project_root.name,
            )
            self.save(state)
            return state

        return PersistedProjectState(title=f"{self.project_root.name} State")

    def save(self, state: PersistedProjectState) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._write_markdown(state)
        self.persisted_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")

    def _write_markdown(self, state: PersistedProjectState) -> None:
        self.state_path.write_text(
            state.render_markdown(self.project_root.name),
            encoding="utf-8",
        )


def _match_line(content: str, pattern: str) -> str:
    match = re.search(pattern, content)
    return match.group(1).strip() if match else ""


def _parse_bullet_section(content: str, pattern: str) -> list[str]:
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return []
    items: list[str] = []
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("*"):
            items.append(stripped[1:].strip())
    return items


def _parse_resume_point(content: str) -> ResumePoint | None:
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
        found = re.search(rf"\*\s*\*\*{re.escape(label)}:\*\*\s*(.*)", section)
        fields[label] = found.group(1).strip() if found else "None"

    if all(value == "None" for value in fields.values()):
        return None

    return ResumePoint(
        last_completed=fields["Last Completed"],
        next_task=fields["Next Task"],
        next_action=fields["Next Action"],
        failure_reason=fields["Failure Reason"],
        checkpoint=fields["Checkpoint"],
    )


def _parse_phase_summaries(content: str) -> dict[str, str]:
    summaries: dict[str, str] = {}
    for match in re.finditer(r"^## Phase Summary:\s*(.+)$", content, re.MULTILINE):
        phase_name = match.group(1).strip()
        start = match.end()
        rest = content[start:]
        next_section = re.search(r"(?m)^## ", rest)
        end = start + next_section.start() if next_section else len(content)
        summaries[phase_name] = content[start:end].strip()
    return summaries


def _parse_phase_reviews(content: str) -> dict[str, PhaseReview]:
    reviews: dict[str, PhaseReview] = {}
    for match in re.finditer(r"^## Phase Review:\s*(.+)$", content, re.MULTILINE):
        phase_name = match.group(1).strip()
        start = match.end()
        rest = content[start:]
        next_section = re.search(r"(?m)^## ", rest)
        end = start + next_section.start() if next_section else len(content)
        section = content[start:end].strip()

        reviewed_at = _match_line(section, r"\*\s*\*\*Reviewed At:\*\*\s*(.*)")
        reviewer = _match_line(section, r"\*\s*\*\*Reviewer:\*\*\s*(.*)")

        findings: list[ReviewFinding] = []
        for finding_match in re.finditer(
            r"^- \[(CRITICAL|WARNING|SUGGESTION)\]\s+(.*?)(?:\s+\(([^():]+)(?::(\d+))?\))?$",
            section,
            re.MULTILINE,
        ):
            severity, message, file_path, line = finding_match.groups()
            findings.append(
                ReviewFinding(
                    severity=ReviewSeverity(severity.lower()),
                    message=message.strip(),
                    file=file_path,
                    line=int(line) if line is not None else None,
                )
            )

        summary_lines: list[str] = []
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped:
                if summary_lines and summary_lines[-1] != "":
                    summary_lines.append("")
                continue
            if stripped.startswith("* **Gate:**"):
                continue
            if stripped.startswith("* **Reviewed At:**"):
                continue
            if stripped.startswith("* **Reviewer:**"):
                continue
            if stripped == "### Findings":
                break
            if stripped.startswith("- ["):
                break
            summary_lines.append(line.rstrip())

        reviews[phase_name] = PhaseReview(
            phase_name=phase_name,
            summary="\n".join(summary_lines).strip(),
            findings=findings,
            reviewed_at=reviewed_at,
            reviewer=reviewer,
            raw_output=section,
        )
    return reviews
