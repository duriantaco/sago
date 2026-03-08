"""Typed models for Sago project state, requirements, and milestones."""

from __future__ import annotations

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
