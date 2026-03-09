from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sago.models.plan import Phase
from sago.state import StateManager

logger = logging.getLogger(__name__)


@dataclass
class TaskStatus:
    id: str
    name: str
    status: Literal["done", "failed", "pending"]
    phase_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "phase_name": self.phase_name,
        }


@dataclass
class FileChange:
    path: str
    size: int
    mtime: float
    is_new: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "is_new": self.is_new,
        }


@dataclass
class PhaseProgress:
    name: str
    done: int
    failed: int
    total: int

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "done": self.done,
            "failed": self.failed,
            "total": self.total,
        }


@dataclass
class ProgressSummary:
    done: int
    failed: int
    total: int
    pct: int

    def to_dict(self) -> dict[str, int]:
        return {
            "done": self.done,
            "failed": self.failed,
            "total": self.total,
            "pct": self.pct,
        }


@dataclass
class MdFileContent:
    filename: str
    content: str
    mtime: float

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "content": self.content,
            "mtime": self.mtime,
        }


@dataclass
class ProjectState:
    tasks: list[TaskStatus]
    progress: ProgressSummary
    phases: list[PhaseProgress]
    recent_files: list[FileChange]
    md_files: list[MdFileContent]
    last_updated: str

    def to_dict(self) -> dict[str, object]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "progress": self.progress.to_dict(),
            "phases": [p.to_dict() for p in self.phases],
            "recent_files": [f.to_dict() for f in self.recent_files],
            "md_files": [m.to_dict() for m in self.md_files],
            "last_updated": self.last_updated,
        }


# Common directories/patterns to always skip
_DEFAULT_IGNORE = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".venv",
    "venv",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "*.egg-info",
    ".planning",
    ".DS_Store",
]

# Common root files to always track even if not in PLAN.md
_COMMON_ROOT_FILES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "README.md",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".env",
    "requirements.txt",
}


def _load_gitignore_patterns(project_path: Path) -> list[str]:
    """Load patterns from .gitignore if it exists."""
    gitignore = project_path / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line.rstrip("/"))
    return patterns


@dataclass
class _IgnoreFilter:
    """Pre-processed ignore patterns split into literal names and glob patterns."""

    literal_names: frozenset[str]
    glob_patterns: tuple[str, ...]

    @classmethod
    def from_patterns(cls, patterns: list[str]) -> _IgnoreFilter:
        literals: set[str] = set()
        globs: list[str] = []
        for p in patterns:
            if any(ch in p for ch in ("*", "?", "[")):
                globs.append(p)
            else:
                literals.add(p)
        return cls(literal_names=frozenset(literals), glob_patterns=tuple(globs))

    def is_ignored(self, rel_path: str) -> bool:
        """Check if a relative path matches any ignore pattern."""
        parts = rel_path.split(os.sep)
        # O(1) lookup for literal names against each path component
        for part in parts:
            if part in self.literal_names:
                return True
        # Glob patterns still need fnmatch
        for pattern in self.glob_patterns:
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
            if fnmatch.fnmatch(rel_path, pattern):
                return True
        return False


_MD_FILES = ["PROJECT.md", "REQUIREMENTS.md", "PLAN.md", "STATE.md", "IMPORTANT.md"]


@dataclass
class _WatcherCache:
    """Internal mutable state for ProjectWatcher, grouped to reduce field count."""

    plan_files: set[str] = field(default_factory=set)
    baseline_mtimes: dict[str, float] = field(default_factory=dict)
    state_mtime: float = 0.0
    cached_tasks: list[TaskStatus] = field(default_factory=list)
    md_mtimes: dict[str, float] = field(default_factory=dict)
    md_contents: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectWatcher:
    project_path: Path
    plan_phases: list[Phase]
    interval: float = 1.0

    _ignore: _IgnoreFilter = field(init=False)
    _cache: _WatcherCache = field(default_factory=_WatcherCache, init=False)

    def __post_init__(self) -> None:
        raw_patterns = _DEFAULT_IGNORE + _load_gitignore_patterns(self.project_path)
        self._ignore = _IgnoreFilter.from_patterns(raw_patterns)

        # Collect all files mentioned in plan tasks
        for phase in self.plan_phases:
            for task in phase.tasks:
                for f in task.files:
                    self._cache.plan_files.add(f)

        # Take baseline snapshot of existing files
        self._cache.baseline_mtimes = self._get_file_mtimes()

    def poll(self) -> ProjectState:
        """Read STATE.md + scan files. Called by HTTP handler per request."""
        tasks = self._parse_state()
        recent_files = self._scan_files()
        md_files = self._read_md_files()

        # Build phase progress
        phase_map: dict[str, PhaseProgress] = {}
        for phase in self.plan_phases:
            phase_map[phase.name] = PhaseProgress(
                name=phase.name, done=0, failed=0, total=len(phase.tasks)
            )

        done_total = 0
        failed_total = 0
        total = len(tasks)
        for t in tasks:
            if t.status == "done":
                done_total += 1
                if t.phase_name in phase_map:
                    phase_map[t.phase_name].done += 1
            elif t.status == "failed":
                failed_total += 1
                if t.phase_name in phase_map:
                    phase_map[t.phase_name].failed += 1

        pct = round(done_total / total * 100) if total > 0 else 0

        return ProjectState(
            tasks=tasks,
            progress=ProgressSummary(done=done_total, failed=failed_total, total=total, pct=pct),
            phases=list(phase_map.values()),
            recent_files=recent_files,
            md_files=md_files,
            last_updated=datetime.now(UTC).isoformat(),
        )

    def _read_md_files(self) -> list[MdFileContent]:
        """Read .md project files, using mtime cache to avoid unnecessary re-reads."""
        result: list[MdFileContent] = []
        for filename in _MD_FILES:
            md_entry = self._read_single_md(filename)
            if md_entry is not None:
                result.append(md_entry)
        return result

    def _read_single_md(self, filename: str) -> MdFileContent | None:
        """Read a single .md file, returning *None* if unavailable."""
        filepath = self.project_path / filename
        if not filepath.exists():
            return None
        try:
            mtime = os.stat(filepath).st_mtime
        except OSError as exc:
            logger.debug("Cannot stat %s: %s", filepath, exc)
            return None
        if mtime != self._cache.md_mtimes.get(filename):
            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("Cannot read %s: %s", filepath, exc)
                return None
            self._cache.md_mtimes[filename] = mtime
            self._cache.md_contents[filename] = content
        content = self._cache.md_contents.get(filename, "")
        return MdFileContent(filename=filename, content=content, mtime=mtime)

    def _parse_state(self) -> list[TaskStatus]:
        """Parse STATE.md for task completion markers [✓] and [✗]."""
        state_file = self.project_path / "STATE.md"
        if not state_file.exists():
            # All tasks pending
            return [
                TaskStatus(id=t.id, name=t.name, status="pending", phase_name=p.name)
                for p in self.plan_phases
                for t in p.tasks
            ]

        # Check if STATE.md has been modified
        try:
            mtime = os.stat(state_file).st_mtime
        except OSError as exc:
            logger.debug("Cannot stat STATE.md, assuming stale: %s", exc)
            mtime = 0.0

        if mtime != self._cache.state_mtime or not self._cache.cached_tasks:
            self._cache.state_mtime = mtime
            state_mgr = StateManager(state_file)
            task_states = state_mgr.get_task_states(self.plan_phases)

            # Build task name/phase lookup from plan
            task_info: dict[str, tuple[str, str]] = {}
            for p in self.plan_phases:
                for t in p.tasks:
                    task_info[t.id] = (t.name, p.name)

            self._cache.cached_tasks = [
                TaskStatus(
                    id=ts.task_id,
                    name=task_info.get(ts.task_id, (ts.task_id, ""))[0],
                    status=ts.status.value,  # type: ignore[arg-type]
                    phase_name=task_info.get(ts.task_id, ("", ""))[1],
                )
                for ts in task_states
            ]

        return self._cache.cached_tasks

    def _get_file_mtimes(self) -> dict[str, float]:
        """Get mtimes for tracked files in the project directory."""
        result: dict[str, float] = {}
        self._collect_root_file_mtimes(result)
        self._collect_subdir_plan_file_mtimes(result)
        return result

    def _collect_root_file_mtimes(self, result: dict[str, float]) -> None:
        """Scan root directory entries and record mtimes for tracked files."""
        try:
            entries = list(os.scandir(self.project_path))
        except OSError as exc:
            logger.debug("Cannot scan project directory: %s", exc)
            return

        for entry in entries:
            if not entry.is_file():
                continue
            rel = entry.name
            if rel not in _COMMON_ROOT_FILES and rel not in self._cache.plan_files:
                continue
            if self._ignore.is_ignored(rel):
                continue
            try:
                result[rel] = entry.stat().st_mtime
            except OSError as exc:
                logger.debug("Cannot stat root file %s: %s", rel, exc)

    def _collect_subdir_plan_file_mtimes(self, result: dict[str, float]) -> None:
        """Record mtimes for plan files that live in subdirectories."""
        for plan_file in self._cache.plan_files:
            if os.sep not in plan_file and "/" not in plan_file:
                continue
            full = self.project_path / plan_file
            try:
                result[plan_file] = os.stat(full).st_mtime
            except OSError as exc:
                logger.debug("Plan file not found %s: %s", plan_file, exc)

    def _safe_file_size(self, rel_path: str) -> int:
        """Return file size in bytes, defaulting to 0 on error."""
        try:
            return os.stat(self.project_path / rel_path).st_size
        except OSError as exc:
            logger.debug("Cannot stat file size for %s: %s", rel_path, exc)
            return 0

    def _scan_files(self) -> list[FileChange]:
        """Scan project dir for new/changed files since baseline."""
        current = self._get_file_mtimes()
        changes: list[FileChange] = []

        for path, mtime in current.items():
            baseline_mtime = self._cache.baseline_mtimes.get(path)
            if baseline_mtime is None:
                size = self._safe_file_size(path)
                changes.append(FileChange(path=path, size=size, mtime=mtime, is_new=True))
            elif mtime > baseline_mtime:
                size = self._safe_file_size(path)
                changes.append(FileChange(path=path, size=size, mtime=mtime, is_new=False))

        # Sort by mtime descending (most recent first)
        changes.sort(key=lambda c: c.mtime, reverse=True)
        return changes
