"""Typed models for Sago project state, requirements, and milestones."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    """Status of a task in the execution state."""

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskState(BaseModel):
    """Status of a single task."""

    task_id: str
    status: TaskStatus
    note: str = ""


class ReviewSeverity(StrEnum):
    """Severity level for a phase-review finding."""

    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ReviewFinding(BaseModel):
    """A single structured review finding."""

    severity: ReviewSeverity
    message: str
    file: str | None = None
    line: int | None = None

    def location(self) -> str:
        if self.file and self.line is not None:
            return f"{self.file}:{self.line}"
        if self.file:
            return self.file
        return ""


class PhaseGateStatus(StrEnum):
    """Gate state for a completed phase."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    BLOCKED = "blocked"


class PhaseReview(BaseModel):
    """Structured review result for a completed phase."""

    phase_name: str
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    reviewed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    reviewer: str = ""
    raw_output: str = ""

    @property
    def gate_status(self) -> PhaseGateStatus:
        if any(finding.severity == ReviewSeverity.CRITICAL for finding in self.findings):
            return PhaseGateStatus.BLOCKED
        return PhaseGateStatus.APPROVED

    def blocking_findings(self) -> list[ReviewFinding]:
        return [
            finding
            for finding in self.findings
            if finding.severity == ReviewSeverity.CRITICAL
        ]

    def to_markdown(self) -> str:
        lines = [
            f"* **Gate:** {self.gate_status.value}",
            f"* **Reviewed At:** {self.reviewed_at}",
        ]
        if self.reviewer:
            lines.append(f"* **Reviewer:** {self.reviewer}")
        if self.summary:
            lines.extend(["", self.summary.strip()])
        if self.findings:
            lines.extend(["", "### Findings", ""])
            for finding in self.findings:
                location = finding.location()
                suffix = f" ({location})" if location else ""
                lines.append(
                    f"- [{finding.severity.value.upper()}] {finding.message}{suffix}"
                )
        return "\n".join(lines).strip()

    @classmethod
    def from_legacy_summary(cls, phase_name: str, summary: str) -> PhaseReview:
        return cls(
            phase_name=phase_name,
            summary=summary.strip(),
            raw_output=summary.strip(),
            reviewer="legacy",
        )


class ResumePoint(BaseModel):
    """Where to resume execution after interruption."""

    last_completed: str
    next_task: str
    next_action: str
    failure_reason: str = "None"
    checkpoint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "last_completed": self.last_completed,
            "next_task": self.next_task,
            "next_action": self.next_action,
            "failure_reason": self.failure_reason,
            "checkpoint": self.checkpoint,
        }


class ProjectState(BaseModel):
    """Overall project execution state."""

    active_phase: str = ""
    current_task: str = ""
    task_states: list[TaskState] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    resume_point: ResumePoint | None = None
    phase_reviews: dict[str, PhaseReview] = Field(default_factory=dict)

    def completed_task_ids(self) -> set[str]:
        """Return IDs of completed tasks."""
        return {ts.task_id for ts in self.task_states if ts.status == TaskStatus.DONE}

    def failed_task_ids(self) -> set[str]:
        """Return IDs of failed tasks."""
        return {ts.task_id for ts in self.task_states if ts.status == TaskStatus.FAILED}

    def pending_task_ids(self) -> set[str]:
        """Return IDs of pending tasks."""
        return {ts.task_id for ts in self.task_states if ts.status == TaskStatus.PENDING}

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> ProjectState:
        """Deserialize from JSON string."""
        return cls.model_validate_json(data)


class Requirement(BaseModel):
    """A single requirement from REQUIREMENTS.md."""

    id: str
    description: str
    completed: bool = False
    version: str = "V1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "completed": self.completed,
            "version": self.version,
        }


class Milestone(BaseModel):
    """A milestone from ROADMAP.md."""

    id: str
    phase: str
    description: str
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "description": self.description,
            "completed": self.completed,
        }


class Requirements(BaseModel):
    """Collection of requirements."""

    requirements: list[Requirement] = Field(default_factory=list)


class Roadmap(BaseModel):
    """Collection of milestones."""

    milestones: list[Milestone] = Field(default_factory=list)
