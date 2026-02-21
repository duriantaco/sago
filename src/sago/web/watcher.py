from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sago.core.parser import MarkdownParser, Phase


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


def _is_ignored(rel_path: str, ignore_patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern."""
    parts = rel_path.split(os.sep)
    for pattern in ignore_patterns:
        # Match against each path component
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
        # Also try matching the full relative path
        if fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


_MD_FILES = ["PROJECT.md", "REQUIREMENTS.md", "PLAN.md", "STATE.md", "IMPORTANT.md"]


@dataclass
class ProjectWatcher:
    project_path: Path
    plan_phases: list[Phase]
    interval: float = 1.0

    _parser: MarkdownParser = field(default_factory=MarkdownParser, init=False)
    _ignore_patterns: list[str] = field(default_factory=list, init=False)
    _plan_files: set[str] = field(default_factory=set, init=False)
    _baseline_mtimes: dict[str, float] = field(default_factory=dict, init=False)
    _state_mtime: float = field(default=0.0, init=False)
    _cached_tasks: list[TaskStatus] = field(default_factory=list, init=False)
    _md_mtimes: dict[str, float] = field(default_factory=dict, init=False)
    _md_contents: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._ignore_patterns = _DEFAULT_IGNORE + _load_gitignore_patterns(self.project_path)

        # Collect all files mentioned in plan tasks
        for phase in self.plan_phases:
            for task in phase.tasks:
                for f in task.files:
                    self._plan_files.add(f)

        # Take baseline snapshot of existing files
        self._baseline_mtimes = self._get_file_mtimes()

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
            filepath = self.project_path / filename
            if not filepath.exists():
                continue
            try:
                mtime = os.stat(filepath).st_mtime
            except OSError:
                continue
            if mtime != self._md_mtimes.get(filename):
                try:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                self._md_mtimes[filename] = mtime
                self._md_contents[filename] = content
            content = self._md_contents.get(filename, "")
            result.append(MdFileContent(filename=filename, content=content, mtime=mtime))
        return result

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
        except OSError:
            mtime = 0.0

        if mtime != self._state_mtime or not self._cached_tasks:
            self._state_mtime = mtime
            content = state_file.read_text(encoding="utf-8", errors="replace")
            parsed = self._parser.parse_state_tasks(content, self.plan_phases)
            self._cached_tasks = [
                TaskStatus(
                    id=t["id"],
                    name=t["name"],
                    status=t["status"],  # type: ignore[arg-type]
                    phase_name=t["phase_name"],
                )
                for t in parsed
            ]

        return self._cached_tasks

    def _get_file_mtimes(self) -> dict[str, float]:
        """Get mtimes for tracked files in the project directory."""
        result: dict[str, float] = {}
        try:
            for entry in os.scandir(self.project_path):
                if entry.is_file():
                    rel = entry.name
                    if rel in _COMMON_ROOT_FILES or rel in self._plan_files:
                        if not _is_ignored(rel, self._ignore_patterns):
                            try:
                                result[rel] = entry.stat().st_mtime
                            except OSError:
                                pass
        except OSError:
            pass

        # Also scan subdirectories for plan files
        for plan_file in self._plan_files:
            if os.sep in plan_file or "/" in plan_file:
                full = self.project_path / plan_file
                try:
                    result[plan_file] = os.stat(full).st_mtime
                except OSError:
                    pass

        return result

    def _scan_files(self) -> list[FileChange]:
        """Scan project dir for new/changed files since baseline."""
        current = self._get_file_mtimes()
        changes: list[FileChange] = []

        for path, mtime in current.items():
            baseline_mtime = self._baseline_mtimes.get(path)
            if baseline_mtime is None:
                # New file
                try:
                    size = os.stat(self.project_path / path).st_size
                except OSError:
                    size = 0
                changes.append(FileChange(path=path, size=size, mtime=mtime, is_new=True))
            elif mtime > baseline_mtime:
                # Modified file
                try:
                    size = os.stat(self.project_path / path).st_size
                except OSError:
                    size = 0
                changes.append(FileChange(path=path, size=size, mtime=mtime, is_new=False))

        # Sort by mtime descending (most recent first)
        changes.sort(key=lambda c: c.mtime, reverse=True)
        return changes
