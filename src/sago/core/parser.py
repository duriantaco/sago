import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "files": self.files,
            "action": self.action,
            "verify": self.verify,
            "done": self.done,
            "phase_name": self.phase_name,
        }


@dataclass
class Phase:
    """Represents a phase containing multiple tasks."""

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
    """Represents a requirement from REQUIREMENTS.md."""

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
    """Represents a milestone from ROADMAP.md."""

    id: str
    phase: str
    description: str
    completed: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert milestone to dictionary."""
        return {
            "id": self.id,
            "phase": self.phase,
            "description": self.description,
            "completed": self.completed,
        }


class MarkdownParser:
    """Parser for sago markdown and XML content."""

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

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}") from e

        phases = []

        for phase_elem in root.findall("phase"):
            phase_name = phase_elem.get("name", "Unknown Phase")
            desc_elem = phase_elem.find("description")
            phase_description = desc_elem.text.strip() if desc_elem is not None else ""

            tasks = []
            for task_elem in phase_elem.findall("task"):
                task_id = task_elem.get("id", "")

                name_elem = task_elem.find("name")
                files_elem = task_elem.find("files")
                action_elem = task_elem.find("action")
                verify_elem = task_elem.find("verify")
                done_elem = task_elem.find("done")

                # Extract files list
                files = []
                if files_elem is not None and files_elem.text:
                    files = [
                        f.strip()
                        for f in files_elem.text.strip().split("\n")
                        if f.strip()
                    ]

                task = Task(
                    id=task_id,
                    name=name_elem.text.strip() if name_elem is not None else "",
                    files=files,
                    action=action_elem.text.strip() if action_elem is not None else "",
                    verify=verify_elem.text.strip() if verify_elem is not None else "",
                    done=done_elem.text.strip() if done_elem is not None else "",
                    phase_name=phase_name,
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

            # Check for version headers
            if line.startswith("### V"):
                version_match = re.match(r"### (V\d+)", line)
                if version_match:
                    current_version = version_match.group(1)
                continue

            # Parse requirement line
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

            # Update section tracking
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

        return state

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
