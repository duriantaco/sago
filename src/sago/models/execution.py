"""Typed models for structured execution tracking and failure classification."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from sago.models.state import TaskStatus


class FailureCategory(StrEnum):
    """Category of a task verification failure."""

    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    RUNTIME_ERROR = "runtime_error"
    ASSERTION_FAILURE = "assertion_failure"
    ENVIRONMENT_MISSING = "environment_missing"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


_FAILURE_PATTERNS: list[tuple[re.Pattern[str], FailureCategory]] = [
    (re.compile(r"SyntaxError:", re.IGNORECASE), FailureCategory.SYNTAX_ERROR),
    (re.compile(r"IndentationError:", re.IGNORECASE), FailureCategory.SYNTAX_ERROR),
    (re.compile(r"TabError:", re.IGNORECASE), FailureCategory.SYNTAX_ERROR),
    (re.compile(r"ModuleNotFoundError:", re.IGNORECASE), FailureCategory.IMPORT_ERROR),
    (re.compile(r"ImportError:", re.IGNORECASE), FailureCategory.IMPORT_ERROR),
    (re.compile(r"No module named", re.IGNORECASE), FailureCategory.IMPORT_ERROR),
    (re.compile(r"AssertionError:", re.IGNORECASE), FailureCategory.ASSERTION_FAILURE),
    (re.compile(r"FAILED.*assert", re.IGNORECASE), FailureCategory.ASSERTION_FAILURE),
    (re.compile(r"assert\w* failed", re.IGNORECASE), FailureCategory.ASSERTION_FAILURE),
    (re.compile(r"command not found", re.IGNORECASE), FailureCategory.ENVIRONMENT_MISSING),
    (re.compile(r"not recognized as.*command", re.IGNORECASE), FailureCategory.ENVIRONMENT_MISSING),
    (re.compile(r"No such file or directory", re.IGNORECASE), FailureCategory.ENVIRONMENT_MISSING),
    (re.compile(r"TimeoutError:", re.IGNORECASE), FailureCategory.TIMEOUT),
    (re.compile(r"timed?\s*out", re.IGNORECASE), FailureCategory.TIMEOUT),
    (re.compile(r"RuntimeError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"TypeError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"ValueError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"KeyError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"AttributeError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"NameError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"IndexError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"ZeroDivisionError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"FileNotFoundError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"PermissionError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (re.compile(r"OSError:", re.IGNORECASE), FailureCategory.RUNTIME_ERROR),
    (
        re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
        FailureCategory.RUNTIME_ERROR,
    ),
]


def classify_failure(stderr: str, exit_code: int) -> FailureCategory:
    """Classify a verification failure based on stderr output.

    Uses deterministic regex pattern matching — no LLM calls.
    """
    if exit_code == 0:
        return FailureCategory.UNKNOWN

    for pattern, category in _FAILURE_PATTERNS:
        if pattern.search(stderr):
            return category

    return FailureCategory.UNKNOWN


class VerifierResult(BaseModel):
    """Structured result of a task verification command."""

    task_id: str
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    failure_category: FailureCategory | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class ExecutionRecord(BaseModel):
    """Record of a single task execution attempt."""

    task_id: str
    attempt: int
    receipt_id: str | None = None
    verifier_result: VerifierResult | None = None
    files_changed: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class CheckpointReceipt(BaseModel):
    """Builder-supplied verification receipt attached to a checkpoint."""

    receipt_id: str = ""
    task_id: str | None = None
    status: TaskStatus | None = None
    verify_command: str = ""
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    files_changed: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    builder: str = ""
    git_head: str = ""
    timed_out: bool = False

    def finalized(self, task_id: str, status: TaskStatus) -> CheckpointReceipt:
        """Normalize defaults and validate task/status consistency."""
        resolved_task_id = self.task_id or task_id
        if self.task_id and self.task_id != task_id:
            raise ValueError(
                f"Receipt task_id {self.task_id} does not match checkpoint task_id {task_id}"
            )

        resolved_status = self.status or status
        if self.status is not None and self.status != status:
            raise ValueError(
                f"Receipt status {self.status.value} does not match checkpoint status {status.value}"
            )
        if resolved_status == TaskStatus.DONE and self.exit_code != 0:
            raise ValueError("A done checkpoint receipt must have exit_code 0")
        if resolved_status == TaskStatus.FAILED and self.exit_code == 0:
            raise ValueError("A failed checkpoint receipt must have a non-zero exit_code")

        resolved_receipt_id = self.receipt_id or (
            f"receipt-{resolved_task_id}-{self.recorded_at.strftime('%Y%m%dT%H%M%SZ')}"
        )

        return self.model_copy(
            update={
                "receipt_id": resolved_receipt_id,
                "task_id": resolved_task_id,
                "status": resolved_status,
            }
        )

    def to_execution_record(self, attempt: int) -> ExecutionRecord:
        """Convert a receipt into a canonical execution-history record."""
        task_id = self.task_id or ""
        failure_category = None if self.exit_code == 0 else classify_failure(self.stderr, self.exit_code)
        verifier_result = VerifierResult(
            task_id=task_id,
            command=self.verify_command,
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
            duration_ms=self.duration_ms,
            timed_out=self.timed_out,
            failure_category=failure_category,
            timestamp=self.recorded_at,
        )
        return ExecutionRecord(
            task_id=task_id,
            attempt=attempt,
            receipt_id=self.receipt_id,
            verifier_result=verifier_result,
            files_changed=list(self.files_changed),
            timestamp=self.recorded_at,
        )


class ExecutionHistory(BaseModel):
    """History of all task execution attempts."""

    records: list[ExecutionRecord] = Field(default_factory=list)

    def failures_for_task(self, task_id: str) -> list[ExecutionRecord]:
        """Return failed execution records for a specific task."""
        return [
            r
            for r in self.records
            if r.task_id == task_id
            and r.verifier_result is not None
            and r.verifier_result.exit_code != 0
        ]

    def repeated_failures(self, threshold: int = 2) -> list[str]:
        """Return task IDs that failed >= threshold times."""
        failure_counts: dict[str, int] = {}
        for record in self.records:
            if record.verifier_result is not None and record.verifier_result.exit_code != 0:
                failure_counts[record.task_id] = failure_counts.get(record.task_id, 0) + 1
        return [tid for tid, count in failure_counts.items() if count >= threshold]

    def attempts_for_task(self, task_id: str) -> int:
        """Return the number of recorded attempts for a task."""
        return sum(1 for record in self.records if record.task_id == task_id)

    def tasks_with_successful_receipts(self) -> set[str]:
        """Return task IDs that have at least one successful receipt-backed verification."""
        return {
            record.task_id
            for record in self.records
            if record.verifier_result is not None and record.verifier_result.exit_code == 0
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> ExecutionHistory:
        """Deserialize from JSON string."""
        return cls.model_validate_json(data)
