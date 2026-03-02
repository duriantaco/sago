import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Task:
    id: str
    name: str
    files: list[str]
    action: str
    verify: str
    done: str
    phase_name: str = ""
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "files": self.files,
            "action": self.action,
            "verify": self.verify,
            "done": self.done,
            "phase_name": self.phase_name,
            "depends_on": self.depends_on,
        }


@dataclass
class Phase:
    name: str
    description: str
    tasks: list[Task]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass
class Requirement:
    id: str
    description: str
    completed: bool
    version: str = "V1"

    def to_dict(self) -> dict[str, Any]:
        """Convert requirement to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "completed": self.completed,
            "version": self.version,
        }


@dataclass
class Milestone:
    id: str
    phase: str
    description: str
    completed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "description": self.description,
            "completed": self.completed,
        }


@dataclass
class ResumePoint:
    last_completed: str
    next_task: str
    next_action: str
    failure_reason: str
    checkpoint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "last_completed": self.last_completed,
            "next_task": self.next_task,
            "next_action": self.next_action,
            "failure_reason": self.failure_reason,
            "checkpoint": self.checkpoint,
        }


class MarkdownParser:
    def parse_xml_tasks(self, content: str) -> list[Phase]:
        xml_pattern = r"```xml\s*(.*?)\s*```"
        xml_match = re.search(xml_pattern, content, re.DOTALL)

        if xml_match:
            xml_content = xml_match.group(1)
        else:
            raw_pattern = r"(<phases\b.*?</phases>)"
            raw_match = re.search(raw_pattern, content, re.DOTALL)
            if not raw_match:
                raise ValueError("No XML task block found in content")
            xml_content = raw_match.group(1)

        # Sanitize bare & in text content (common LLM output issue)
        xml_content = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xml_content)

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}") from e

        phases = []

        for phase_elem in root.findall("phase"):
            phase_name = phase_elem.get("name", "Unknown Phase")
            desc_elem = phase_elem.find("description")
            phase_description = (desc_elem.text or "").strip() if desc_elem is not None else ""

            tasks = []
            for task_elem in phase_elem.findall("task"):
                task_id = task_elem.get("id", "")
                depends_on_raw = task_elem.get("depends_on", "")
                depends_on = [d.strip() for d in depends_on_raw.split(",") if d.strip()]

                name_elem = task_elem.find("name")
                files_elem = task_elem.find("files")
                action_elem = task_elem.find("action")
                verify_elem = task_elem.find("verify")
                done_elem = task_elem.find("done")

                files = []
                if files_elem is not None and files_elem.text:
                    files = [f.strip() for f in files_elem.text.strip().split("\n") if f.strip()]

                task = Task(
                    id=task_id,
                    name=(name_elem.text or "").strip() if name_elem is not None else "",
                    files=files,
                    action=(action_elem.text or "").strip() if action_elem is not None else "",
                    verify=(verify_elem.text or "").strip() if verify_elem is not None else "",
                    done=(done_elem.text or "").strip() if done_elem is not None else "",
                    phase_name=phase_name,
                    depends_on=depends_on,
                )
                tasks.append(task)

            phases.append(Phase(name=phase_name, description=phase_description, tasks=tasks))

        return phases

    def parse_requirements(self, content: str) -> list[Requirement]:
        """Parse requirements from REQUIREMENTS.md.

        Args:
            content: Content of REQUIREMENTS.md file

        Returns:
            List of Requirement objects
        """
        requirements = []
        current_version = "V1"

        req_pattern = r"^\* \[([ x])\] \*\*([A-Z]+-\d+):\*\* (.+)$"

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("### V"):
                version_match = re.match(r"### (V\d+)", line)
                if version_match:
                    current_version = version_match.group(1)
                continue

            match = re.match(req_pattern, line)
            if match:
                completed = match.group(1) == "x"
                req_id = match.group(2)
                description = match.group(3)

                requirements.append(
                    Requirement(
                        id=req_id,
                        description=description,
                        completed=completed,
                        version=current_version,
                    )
                )

        return requirements

    def parse_roadmap(self, content: str) -> list[Milestone]:
        """Parse milestones from ROADMAP.md.

        Args:
            content: Content of ROADMAP.md file

        Returns:
            List of Milestone objects
        """
        milestones = []
        current_phase = ""

        milestone_pattern = r"^\* \[([ x])\] \*\*([^:]+):\*\* (.+)$"

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("### Phase"):
                phase_match = re.match(r"### (.+?)$", line)
                if phase_match:
                    current_phase = phase_match.group(1)
                continue

            match = re.match(milestone_pattern, line)
            if match:
                completed = match.group(1) == "x"
                milestone_id = match.group(2)
                description = match.group(3)

                milestones.append(
                    Milestone(
                        id=milestone_id,
                        phase=current_phase,
                        description=description,
                        completed=completed,
                    )
                )

        return milestones

    def parse_resume_point(self, content: str) -> ResumePoint | None:
        """Parse the Resume Point section from STATE.md.

        Returns None if the section is missing or all fields are "None".
        """
        match = re.search(r"## Resume Point\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if not match:
            return None

        section = match.group(1)
        fields: dict[str, str] = {}
        for label in ("Last Completed", "Next Task", "Next Action", "Failure Reason", "Checkpoint"):
            m = re.search(rf"\*\s*\*\*{re.escape(label)}:\*\*\s*(.*)", section)
            fields[label] = m.group(1).strip() if m else "None"

        if all(v == "None" for v in fields.values()):
            return None

        return ResumePoint(
            last_completed=fields["Last Completed"],
            next_task=fields["Next Task"],
            next_action=fields["Next Action"],
            failure_reason=fields["Failure Reason"],
            checkpoint=fields["Checkpoint"],
        )

    def parse_state(self, content: str) -> dict[str, Any]:
        """Parse current state from STATE.md.

        Args:
            content: Content of STATE.md file

        Returns:
            Dictionary with state information
        """
        state: dict[str, Any] = {
            "active_phase": "",
            "current_task": "",
            "decisions": [],
            "blockers": [],
        }

        current_section = ""
        section_map = {
            "### Current Context": "context",
            "### Decisions Log": "decisions",
            "### Known Blockers": "blockers",
        }

        for line in content.split("\n"):
            line = line.strip()

            if line.startswith("###"):
                current_section = section_map.get(line, "")
                continue

            if current_section == "context":
                if "Active Phase:" in line:
                    state["active_phase"] = line.split("Active Phase:**", 1)[-1].strip()
                elif "Current Task:" in line:
                    state["current_task"] = line.split("Current Task:**", 1)[-1].strip()
            elif current_section in ("decisions", "blockers") and line.startswith("*"):
                state[current_section].append(line[1:].strip())

        state["resume_point"] = self.parse_resume_point(content)

        return state

    def parse_review_prompt(self, content: str) -> str:
        """Extract the <review> tag content from <phases> XML.

        Returns the review prompt text, or empty string if no <review> tag exists.
        """
        xml_pattern = r"```xml\s*(.*?)\s*```"
        xml_match = re.search(xml_pattern, content, re.DOTALL)

        if xml_match:
            xml_content = xml_match.group(1)
        else:
            raw_pattern = r"(<phases\b.*?</phases>)"
            raw_match = re.search(raw_pattern, content, re.DOTALL)
            if not raw_match:
                return ""
            xml_content = raw_match.group(1)

        xml_content = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xml_content)

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return ""

        review_elem = root.find("review")
        if review_elem is not None and review_elem.text:
            return review_elem.text.strip()
        return ""

    def parse_dependencies(self, content: str) -> list[str]:
        """Extract <package> elements from <dependencies> in PLAN.md XML.

        Returns e.g. ["flask>=2.0", "requests", "pydantic>=2.0"].
        Returns [] if no <dependencies> element found.
        """
        xml_pattern = r"```xml\s*(.*?)\s*```"
        xml_match = re.search(xml_pattern, content, re.DOTALL)

        if xml_match:
            xml_content = xml_match.group(1)
        else:
            raw_pattern = r"(<phases\b.*?</phases>)"
            raw_match = re.search(raw_pattern, content, re.DOTALL)
            if not raw_match:
                return []
            xml_content = raw_match.group(1)

        xml_content = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xml_content)

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return []

        deps_elem = root.find("dependencies")
        if deps_elem is None:
            return []

        return [
            pkg.text.strip()
            for pkg in deps_elem.findall("package")
            if pkg.text and pkg.text.strip()
        ]

    def parse_state_tasks(self, content: str, plan_phases: list[Phase]) -> list[dict[str, str]]:
        """Parse STATE.md and match against plan tasks.

        Returns list of {id, name, status: 'done'|'failed'|'pending', phase_name}
        for every task in the plan. Tasks not mentioned in STATE.md are 'pending'.
        """
        done_ids: set[str] = set()
        failed_ids: set[str] = set()

        for line in content.split("\n"):
            line = line.strip()
            m = re.match(r"\[✓\]\s+(\d+\.\d+):", line)
            if m:
                done_ids.add(m.group(1))
                continue
            m = re.match(r"\[✗\]\s+(\d+\.\d+):", line)
            if m:
                failed_ids.add(m.group(1))

        results: list[dict[str, str]] = []
        for phase in plan_phases:
            for task in phase.tasks:
                if task.id in done_ids:
                    status = "done"
                elif task.id in failed_ids:
                    status = "failed"
                else:
                    status = "pending"
                results.append(
                    {
                        "id": task.id,
                        "name": task.name,
                        "status": status,
                        "phase_name": phase.name,
                    }
                )
        return results

    def parse_plan_file(self, file_path: Path) -> list[Phase]:
        content = file_path.read_text(encoding="utf-8")
        return self.parse_xml_tasks(content)

    def parse_requirements_file(self, file_path: Path) -> list[Requirement]:
        """Parse REQUIREMENTS.md file and return requirements.

        Args:
            file_path: Path to REQUIREMENTS.md file

        Returns:
            List of Requirement objects
        """
        content = file_path.read_text(encoding="utf-8")
        return self.parse_requirements(content)

    def parse_roadmap_file(self, file_path: Path) -> list[Milestone]:
        content = file_path.read_text(encoding="utf-8")
        return self.parse_roadmap(content)

    def parse_state_file(self, file_path: Path) -> dict[str, Any]:
        content = file_path.read_text(encoding="utf-8")
        return self.parse_state(content)
