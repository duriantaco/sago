"""Semantic plan validator — catches structural and semantic issues in plans."""

from __future__ import annotations

import re
from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel

from sago.models.plan import Plan

# Commands that should never appear in verify fields.
# Matched against the first token of each command in a pipeline.
DANGEROUS_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "dd",
        "mkfs",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "kill",
        "killall",
        "pkill",
        "chmod",
        "chown",
        "mount",
        "umount",
        "fdisk",
        "format",
        "wget",
        "curl",
        "nc",
        "ncat",
        "ssh",
        "scp",
        "rsync",
        "eval",
        "exec",
        "sudo",
        "su",
        "pip install",
        "npm install",
        "apt",
        "brew",
        "yum",
        "dnf",
        "pacman",
    }
)

# Patterns that indicate shell injection risk in verify commands
DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r"\$\(", "command substitution $()"),
    (r"`[^`]+`", "backtick command substitution"),
    (r"\|\s*(bash|sh|zsh|dash|csh)", "piping to shell"),
    (r">\s*/", "redirect to absolute path"),
    (r"&&\s*rm\b", "chained rm command"),
    (r";\s*rm\b", "chained rm command"),
    (r"\brm\s+-[a-z]*r", "recursive rm"),
    (r"\bcurl\b.*\|\s*(bash|sh|python)", "download-and-execute"),
    (r"\bwget\b.*\|\s*(bash|sh|python)", "download-and-execute"),
]


def check_verify_safety(verify_cmd: str) -> list[str]:
    """Check a verify command for dangerous patterns.

    Returns a list of warning strings (empty = safe).
    This is used both by PlanValidator and by CLI commands like `sago next`.
    """
    warnings: list[str] = []
    if not verify_cmd or not verify_cmd.strip():
        return warnings

    cmd = verify_cmd.strip()

    # Split on pipes and check each segment
    segments = re.split(r"\s*\|\s*", cmd)
    for segment in segments:
        tokens = segment.strip().split()
        if not tokens:
            continue
        first = tokens[0].lower()
        # Check two-token commands like "pip install"
        two_token = f"{first} {tokens[1].lower()}" if len(tokens) > 1 else ""
        if first in DANGEROUS_COMMANDS or two_token in DANGEROUS_COMMANDS:
            warnings.append(f"dangerous command '{first}' in verify")

    # Check patterns
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, cmd):
            warnings.append(f"suspicious pattern: {description}")

    return warnings


class Severity(StrEnum):
    """Severity level of a validation issue."""

    ERROR = "error"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class ValidationIssue(BaseModel):
    """A single validation finding."""

    severity: Severity
    code: str
    message: str
    task_id: str | None = None
    phase_name: str | None = None


class ValidationResult(BaseModel):
    """Result of plan validation."""

    issues: list[ValidationIssue]

    @property
    def valid(self) -> bool:
        """True if no errors (warnings/suggestions are ok)."""
        return not any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def suggestions(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.SUGGESTION]


class PlanValidator:
    """Validates a Plan for structural and semantic correctness."""

    def validate(self, plan: Plan) -> ValidationResult:
        """Run all validation checks and return results."""
        issues: list[ValidationIssue] = []
        issues.extend(self._check_missing_task_ids(plan))
        issues.extend(self._check_duplicate_task_ids(plan))
        issues.extend(self._check_invalid_dependency_refs(plan))
        issues.extend(self._check_dependency_cycles(plan))
        issues.extend(self._check_empty_action(plan))
        issues.extend(self._check_empty_files(plan))
        issues.extend(self._check_cross_phase_backward_deps(plan))
        issues.extend(self._check_empty_verify(plan))
        issues.extend(self._check_missing_done(plan))
        issues.extend(self._check_broad_tasks(plan))
        issues.extend(self._check_duplicate_files_in_phase(plan))
        issues.extend(self._check_too_many_files(plan))
        issues.extend(self._check_single_task_phase(plan))
        issues.extend(self._check_large_phase(plan))
        issues.extend(self._check_over_specified_deps(plan))
        issues.extend(self._check_dangerous_verify(plan))
        return ValidationResult(issues=issues)

    def _check_missing_task_ids(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if not task.id or not task.id.strip():
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="MISSING_TASK_ID",
                        message=f"Task '{task.name}' has no ID",
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_duplicate_task_ids(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        seen: dict[str, str] = {}
        for task in plan.all_tasks():
            if not task.id:
                continue
            if task.id in seen:
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="DUPLICATE_ID",
                        message=f"Task ID '{task.id}' is duplicated (first in {seen[task.id]}, also in {task.phase_name})",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
            else:
                seen[task.id] = task.phase_name
        return issues

    def _check_invalid_dependency_refs(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        valid_ids = plan.task_ids()
        for task in plan.all_tasks():
            for dep_id in task.depends_on:
                if dep_id not in valid_ids:
                    issues.append(
                        ValidationIssue(
                            severity=Severity.ERROR,
                            code="INVALID_DEPENDENCY",
                            message=f"Task '{task.id}' depends on '{dep_id}' which does not exist",
                            task_id=task.id,
                            phase_name=task.phase_name,
                        )
                    )
        return issues

    def _check_dependency_cycles(self, plan: Plan) -> list[ValidationIssue]:
        """Detect cycles using topological sort (Kahn's algorithm)."""
        graph = plan.dependency_graph()
        all_ids = plan.task_ids()

        if not all_ids:
            return []

        # Build in-degree map
        in_degree: dict[str, int] = dict.fromkeys(all_ids, 0)
        adjacency: dict[str, list[str]] = {tid: [] for tid in all_ids}

        for tid, deps in graph.items():
            for dep in deps:
                if dep in all_ids:
                    adjacency[dep].append(tid)
                    in_degree[tid] += 1

        # Kahn's algorithm
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited < len(all_ids):
            cycle_ids = [tid for tid, deg in in_degree.items() if deg > 0]
            return [
                ValidationIssue(
                    severity=Severity.ERROR,
                    code="DEPENDENCY_CYCLE",
                    message=f"Dependency cycle detected involving tasks: {', '.join(sorted(cycle_ids))}",
                )
            ]
        return []

    def _check_empty_action(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if not task.action or not task.action.strip():
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="EMPTY_ACTION",
                        message=f"Task '{task.id}' has no action description",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_empty_files(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if not task.files:
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        code="EMPTY_FILES",
                        message=f"Task '{task.id}' has no files listed",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_cross_phase_backward_deps(self, plan: Plan) -> list[ValidationIssue]:
        """Check for tasks that depend on tasks in later phases."""
        issues = []
        phase_order: dict[str, int] = {}
        task_phase: dict[str, int] = {}

        for i, phase in enumerate(plan.phases):
            phase_order[phase.name] = i
            for task in phase.tasks:
                task_phase[task.id] = i

        for task in plan.all_tasks():
            task_idx = task_phase.get(task.id, 0)
            for dep_id in task.depends_on:
                dep_idx = task_phase.get(dep_id)
                if dep_idx is not None and dep_idx > task_idx:
                    issues.append(
                        ValidationIssue(
                            severity=Severity.ERROR,
                            code="BACKWARD_DEPENDENCY",
                            message=f"Task '{task.id}' depends on '{dep_id}' which is in a later phase",
                            task_id=task.id,
                            phase_name=task.phase_name,
                        )
                    )
        return issues

    # --- Warnings ---

    def _check_empty_verify(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if not task.verify or not task.verify.strip():
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="EMPTY_VERIFY",
                        message=f"Task '{task.id}' has no verification command",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_missing_done(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if not task.done or not task.done.strip():
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="MISSING_DONE",
                        message=f"Task '{task.id}' has no acceptance criteria",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_broad_tasks(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if len(task.action) > 2000:
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="BROAD_TASK",
                        message=f"Task '{task.id}' has a very long action ({len(task.action)} chars) — consider splitting",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_duplicate_files_in_phase(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for phase in plan.phases:
            file_owners: dict[str, list[str]] = defaultdict(list)
            for task in phase.tasks:
                for f in task.files:
                    file_owners[f].append(task.id)
            for f, owners in file_owners.items():
                if len(owners) > 1:
                    issues.append(
                        ValidationIssue(
                            severity=Severity.WARNING,
                            code="DUPLICATE_FILE",
                            message=f"File '{f}' is claimed by multiple tasks in {phase.name}: {', '.join(owners)}",
                            phase_name=phase.name,
                        )
                    )
        return issues

    def _check_too_many_files(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for task in plan.all_tasks():
            if len(task.files) > 8:
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="TOO_MANY_FILES",
                        message=f"Task '{task.id}' touches {len(task.files)} files — consider splitting",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    def _check_dangerous_verify(self, plan: Plan) -> list[ValidationIssue]:
        """Flag verify commands that contain dangerous or suspicious patterns."""
        issues = []
        for task in plan.all_tasks():
            warnings = check_verify_safety(task.verify)
            for warning in warnings:
                issues.append(
                    ValidationIssue(
                        severity=Severity.WARNING,
                        code="DANGEROUS_VERIFY",
                        message=f"Task '{task.id}': {warning}",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues

    # --- Suggestions ---

    def _check_single_task_phase(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for phase in plan.phases:
            if len(phase.tasks) == 1:
                issues.append(
                    ValidationIssue(
                        severity=Severity.SUGGESTION,
                        code="SINGLE_TASK_PHASE",
                        message=f"Phase '{phase.name}' has only 1 task — consider merging with another phase",
                        phase_name=phase.name,
                    )
                )
        return issues

    def _check_large_phase(self, plan: Plan) -> list[ValidationIssue]:
        issues = []
        for phase in plan.phases:
            if len(phase.tasks) > 10:
                issues.append(
                    ValidationIssue(
                        severity=Severity.SUGGESTION,
                        code="LARGE_PHASE",
                        message=f"Phase '{phase.name}' has {len(phase.tasks)} tasks — consider splitting",
                        phase_name=phase.name,
                    )
                )
        return issues

    def _check_over_specified_deps(self, plan: Plan) -> list[ValidationIssue]:
        """Flag tasks that depend on all prior tasks (probably over-specified)."""
        issues = []
        all_tasks = plan.all_tasks()
        for i, task in enumerate(all_tasks):
            if i < 2:
                continue
            prior_ids = {t.id for t in all_tasks[:i]}
            if (
                len(task.depends_on) >= len(prior_ids)
                and prior_ids
                and prior_ids.issubset(set(task.depends_on))
            ):
                issues.append(
                    ValidationIssue(
                        severity=Severity.SUGGESTION,
                        code="OVER_SPECIFIED_DEPS",
                        message=f"Task '{task.id}' depends on all prior tasks — probably over-specified",
                        task_id=task.id,
                        phase_name=task.phase_name,
                    )
                )
        return issues
