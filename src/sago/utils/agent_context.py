"""Repo-local agent context discovery for planning and review workflows.

These files describe how an external coding agent should work in a repo.
Sago reads them to improve planning, handoff, and review, but does not
execute them itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentContextSpec:
    path: str
    kind: str
    description: str


SUPPORTED_AGENT_CONTEXT_FILES: tuple[AgentContextSpec, ...] = (
    AgentContextSpec(
        path="IMPORTANT.md",
        kind="project_rules",
        description="Non-negotiable project rules and constraints",
    ),
    AgentContextSpec(
        path="AGENTS.md",
        kind="shared_agent_instructions",
        description="Shared instructions for coding agents working in this repository",
    ),
    AgentContextSpec(
        path="SKILLS.md",
        kind="agent_capabilities",
        description="Repo-local skills, capabilities, or preferred workflows for coding agents",
    ),
    AgentContextSpec(
        path="CLAUDE.md",
        kind="agent_specific_instructions",
        description="Claude Code instructions and workflow guidance",
    ),
    AgentContextSpec(
        path=".cursorrules",
        kind="agent_specific_instructions",
        description="Cursor rules and editor-agent guidance",
    ),
)


@dataclass(frozen=True)
class AgentContextFile:
    path: str
    kind: str
    description: str
    content: str
    line_count: int
    truncated: bool

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "description": self.description,
            "line_count": self.line_count,
            "truncated": self.truncated,
        }


@dataclass
class AgentContextSnapshot:
    files: list[AgentContextFile] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return bool(self.files)

    @property
    def file_paths(self) -> list[str]:
        return [entry.path for entry in self.files]

    def to_prompt_block(self) -> str:
        if not self.files:
            return ""

        sections = [
            (
                "The repository defines agent context files for the external coding agent "
                "contract. Treat them as workflow constraints, capabilities, and handoff "
                "instructions. Use them to shape task design and review guidance. Sago does "
                "not execute these instructions itself."
            )
        ]
        for entry in self.files:
            sections.append(f"=== {entry.path} ({entry.kind}) ===\n{entry.content}")
        return "\n\n".join(sections)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "count": len(self.files),
            "files": [entry.to_summary_dict() for entry in self.files],
            "errors": list(self.errors),
        }


def load_agent_context(
    project_path: Path,
    *,
    max_chars_per_file: int = 8000,
) -> AgentContextSnapshot:
    """Load supported repo-local agent context files from *project_path*."""
    project_path = Path(project_path)
    snapshot = AgentContextSnapshot()

    for spec in SUPPORTED_AGENT_CONTEXT_FILES:
        file_path = project_path / spec.path
        if not file_path.is_file():
            continue

        try:
            raw_content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            snapshot.errors.append(f"{spec.path}: {exc}")
            continue

        content = raw_content.strip()
        if not content:
            continue

        truncated = len(content) > max_chars_per_file
        if truncated:
            content = content[:max_chars_per_file].rstrip() + "\n... [truncated]"

        snapshot.files.append(
            AgentContextFile(
                path=spec.path,
                kind=spec.kind,
                description=spec.description,
                content=content,
                line_count=len(raw_content.splitlines()),
                truncated=truncated,
            )
        )

    return snapshot
