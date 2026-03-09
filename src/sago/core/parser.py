import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from sago.models.plan import Phase, Task
from sago.models.state import Milestone, Requirement

logger = logging.getLogger(__name__)


def _extract_xml_content(content: str) -> str | None:
    """Extract XML content from markdown fenced block or raw <phases> tag.

    Returns the XML string, or None if no XML block found.
    """
    xml_pattern = r"```xml\s*(.*?)\s*```"
    xml_match = re.search(xml_pattern, content, re.DOTALL)

    if xml_match:
        return xml_match.group(1)

    raw_pattern = r"(<phases\b.*?</phases>)"
    raw_match = re.search(raw_pattern, content, re.DOTALL)
    if raw_match:
        return raw_match.group(1)
    return None


def _sanitize_xml(xml_content: str) -> str:
    """Sanitize bare & in text content (common LLM output issue)."""
    return re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#)", "&amp;", xml_content)


def _parse_xml_root(xml_content: str) -> ET.Element | None:
    """Parse sanitized XML string into an Element, or None on error."""
    sanitized = _sanitize_xml(xml_content)
    try:
        return ET.fromstring(sanitized)
    except ET.ParseError as exc:
        logger.debug("XML parse failed: %s", exc)
        return None


def _parse_task_element(task_elem: ET.Element, phase_name: str) -> Task:
    """Parse a single <task> XML element into a Task model."""
    task_id = task_elem.get("id", "")
    depends_on_raw = task_elem.get("depends_on", "")
    depends_on = [d.strip() for d in depends_on_raw.split(",") if d.strip()]

    name_elem = task_elem.find("name")
    files_elem = task_elem.find("files")
    action_elem = task_elem.find("action")
    verify_elem = task_elem.find("verify")
    done_elem = task_elem.find("done")

    files: list[str] = []
    if files_elem is not None and files_elem.text:
        files = [f.strip() for f in files_elem.text.strip().split("\n") if f.strip()]

    return Task(
        id=task_id,
        name=(name_elem.text or "").strip() if name_elem is not None else "",
        files=files,
        action=(action_elem.text or "").strip() if action_elem is not None else "",
        verify=(verify_elem.text or "").strip() if verify_elem is not None else "",
        done=(done_elem.text or "").strip() if done_elem is not None else "",
        phase_name=phase_name,
        depends_on=depends_on,
    )


def _parse_phase_element(phase_elem: ET.Element) -> Phase:
    """Parse a single <phase> XML element into a Phase model."""
    phase_name = phase_elem.get("name", "Unknown Phase")
    desc_elem = phase_elem.find("description")
    phase_description = (desc_elem.text or "").strip() if desc_elem is not None else ""

    tasks = [_parse_task_element(te, phase_name) for te in phase_elem.findall("task")]
    return Phase(name=phase_name, description=phase_description, tasks=tasks)


class MarkdownParser:
    def parse_xml_tasks(self, content: str) -> list[Phase]:
        xml_content = _extract_xml_content(content)
        if xml_content is None:
            raise ValueError("No XML task block found in content")

        sanitized = _sanitize_xml(xml_content)
        try:
            root = ET.fromstring(sanitized)
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML: {e}") from e

        return [_parse_phase_element(pe) for pe in root.findall("phase")]

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

    def parse_review_prompt(self, content: str) -> str:
        """Extract the <review> tag content from <phases> XML.

        Returns the review prompt text, or empty string if no <review> tag exists.
        """
        xml_content = _extract_xml_content(content)
        if xml_content is None:
            return ""

        root = _parse_xml_root(xml_content)
        if root is None:
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
        xml_content = _extract_xml_content(content)
        if xml_content is None:
            return []

        root = _parse_xml_root(xml_content)
        if root is None:
            return []

        deps_elem = root.find("dependencies")
        if deps_elem is None:
            return []

        return [
            pkg.text.strip()
            for pkg in deps_elem.findall("package")
            if pkg.text and pkg.text.strip()
        ]

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
