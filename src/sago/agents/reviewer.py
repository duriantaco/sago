import logging
import json
import re
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.models import Phase
from sago.models.state import PhaseReview, ReviewFinding, ReviewSeverity
from sago.utils.agent_context import load_agent_context
from sago.utils.paths import safe_resolve
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Reviews completed phase output and produces feedback for subsequent phases."""

    def _build_system_prompt(self) -> str:
        return """You are a senior code reviewer auditing completed work from a project phase.

Rules:
- Review the code that already exists in the project; do not invent new features
- Focus on correctness, requirement alignment, edge cases, security, and maintainability
- Be specific and actionable, with file and line references when possible
- Separate critical issues, warnings, and suggestions clearly
- Honor repo-local agent context files (IMPORTANT.md, AGENTS.md, SKILLS.md, CLAUDE.md, .cursorrules) when present
- Return valid JSON only with this shape:
  {
    "summary": "short human summary",
    "findings": [
      {
        "severity": "critical" | "warning" | "suggestion",
        "message": "what is wrong or what to improve",
        "file": "relative/path.py",
        "line": 12
      }
    ]
  }
- Use an empty findings array when there are no issues.
"""

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Review failed: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
                metadata={
                    "phase_name": context.get(
                        "phase", Phase(name="", description="", tasks=[])
                    ).name
                },
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        phase: Phase = context["phase"]
        project_path = Path(context.get("project_path", "."))
        review_prompt: str = context["review_prompt"]

        self.logger.info(f"Reviewing phase: {phase.name}")

        review_context = self._build_review_context(phase, project_path)
        messages = self._build_review_messages(review_prompt, review_context)

        response = await self._call_llm(messages)
        review = self._parse_review_response(phase.name, response["content"])
        review_output = review.to_markdown()

        tracer.emit(
            "phase_review",
            "ReviewerAgent",
            {
                "phase_name": phase.name,
                "review_length": len(review_output),
                "review_preview": review_output[:2000],
                "gate_status": review.gate_status.value,
                "finding_count": len(review.findings),
            },
        )

        return self._create_result(
            status=AgentStatus.SUCCESS,
            output=review_output,
            metadata={
                "phase_name": phase.name,
                "review_length": len(review_output),
                "phase_review": review.model_dump(mode="json"),
            },
        )

    def _read_file_truncated(self, path: Path, label: str, max_chars: int = 8000) -> str | None:
        """Read a file and return its content truncated to max_chars, or None on failure."""
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n... (truncated)"
            return content
        except (OSError, UnicodeDecodeError) as e:
            self.logger.debug(f"Could not read {label}: {e}")
            return None

    def _build_review_context(self, phase: Phase, project_path: Path) -> str:
        parts: list[str] = []

        parts.append(f"=== PHASE: {phase.name} ===")
        if phase.description:
            parts.append(f"Description: {phase.description}")

        parts.append("\n=== COMPLETED TASKS ===")
        for task in phase.tasks:
            parts.append(f"\nTask {task.id}: {task.name}")
            parts.append(f"  Action: {task.action}")
            parts.append(f"  Files: {', '.join(task.files)}")

        parts.append("\n=== GENERATED FILES ===")
        for task in phase.tasks:
            for file_path_str in task.files:
                file_path = safe_resolve(project_path, file_path_str)
                content = self._read_file_truncated(file_path, file_path_str)
                if content is not None:
                    parts.append(f"\n--- {file_path_str} ---\n{content}")
                elif file_path.exists():
                    parts.append(f"\n--- {file_path_str} --- (could not read)")

        for context_file in ["PROJECT.md", "REQUIREMENTS.md"]:
            ctx_path = project_path / context_file
            content = self._read_file_truncated(ctx_path, context_file, max_chars=4000)
            if content is not None:
                parts.append(f"\n=== {context_file} ===\n{content}")

        agent_context = load_agent_context(project_path, max_chars_per_file=4000)
        if agent_context.present:
            parts.append("\n=== AGENT CONTEXT ===")
            for entry in agent_context.files:
                parts.append(f"\n--- {entry.path} ({entry.kind}) ---\n{entry.content}")

        return "\n".join(parts)

    def _build_review_messages(
        self, review_prompt: str, review_context: str
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": f"""Review the completed phase using the instructions below.

=== REVIEW INSTRUCTIONS ===
{review_prompt}

{review_context}

Provide your review now. Be specific with file names and line references.
Return JSON only.""",
            },
        ]

    def _parse_review_response(self, phase_name: str, content: str) -> PhaseReview:
        payload = self._extract_json_payload(content)
        if payload is not None:
            findings = [
                ReviewFinding(
                    severity=ReviewSeverity(str(item.get("severity", "warning")).lower()),
                    message=str(item.get("message", "")).strip(),
                    file=(str(item["file"]).strip() if item.get("file") else None),
                    line=int(item["line"]) if item.get("line") is not None else None,
                )
                for item in payload.get("findings", [])
                if str(item.get("message", "")).strip()
            ]
            return PhaseReview(
                phase_name=phase_name,
                summary=str(payload.get("summary", "")).strip(),
                findings=findings,
                reviewer="judge",
                raw_output=content.strip(),
            )

        findings = self._parse_legacy_findings(content)
        return PhaseReview(
            phase_name=phase_name,
            summary=content.strip(),
            findings=findings,
            reviewer="judge",
            raw_output=content.strip(),
        )

    def _extract_json_payload(self, content: str) -> dict[str, Any] | None:
        candidates = [content.strip()]
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced:
            candidates.insert(0, fenced.group(1).strip())

        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                for match in re.finditer(r"\{", candidate):
                    try:
                        payload, _ = decoder.raw_decode(candidate[match.start() :])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        return payload
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def _parse_legacy_findings(self, content: str) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for match in re.finditer(
            r"\[(CRITICAL|WARNING|SUGGESTION)\]\s+(.*?)(?:\s+\(([^():]+)(?::(\d+))?\))?$",
            content,
            re.MULTILINE,
        ):
            severity, message, file_path, line = match.groups()
            findings.append(
                ReviewFinding(
                    severity=ReviewSeverity(severity.lower()),
                    message=message.strip(),
                    file=file_path,
                    line=int(line) if line is not None else None,
                )
            )
        return findings
