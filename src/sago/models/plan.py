"""Typed models for Sago plans."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from pydantic import BaseModel, Field


class Task(BaseModel):
    """A single atomic task within a phase."""

    id: str
    name: str
    files: list[str]
    action: str
    verify: str
    done: str
    phase_name: str = ""
    depends_on: list[str] = Field(default_factory=list)

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


class Phase(BaseModel):
    """A group of related tasks."""

    name: str
    description: str
    tasks: list[Task]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tasks": [task.to_dict() for task in self.tasks],
        }


class Dependency(BaseModel):
    """A third-party package dependency."""

    package: str


class ReviewPrompt(BaseModel):
    """Instructions for post-phase code review."""

    content: str


class Plan(BaseModel):
    """A complete project plan with phases, dependencies, and review instructions."""

    phases: list[Phase]
    dependencies: list[Dependency] = Field(default_factory=list)
    review_prompt: ReviewPrompt | None = None

    def all_tasks(self) -> list[Task]:
        """Return all tasks across all phases."""
        return [task for phase in self.phases for task in phase.tasks]

    def get_task(self, task_id: str) -> Task | None:
        """Find a task by ID."""
        for task in self.all_tasks():
            if task.id == task_id:
                return task
        return None

    def task_ids(self) -> set[str]:
        """Return all task IDs in the plan."""
        return {task.id for task in self.all_tasks()}

    def dependency_graph(self) -> dict[str, list[str]]:
        """Return mapping of task_id -> list of task IDs it depends on."""
        return {task.id: list(task.depends_on) for task in self.all_tasks()}

    def dependency_packages(self) -> list[str]:
        """Return list of package strings (e.g. 'flask>=2.0')."""
        return [dep.package for dep in self.dependencies]

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> Plan:
        """Deserialize from JSON string."""
        return cls.model_validate_json(data)

    def to_xml(self) -> str:
        """Render to the XML format used in PLAN.md."""
        root = ET.Element("phases")

        if self.dependencies:
            deps_elem = ET.SubElement(root, "dependencies")
            for dep in self.dependencies:
                pkg_elem = ET.SubElement(deps_elem, "package")
                pkg_elem.text = dep.package

        if self.review_prompt:
            review_elem = ET.SubElement(root, "review")
            review_elem.text = f"\n        {self.review_prompt.content}\n    "

        for phase in self.phases:
            phase_elem = ET.SubElement(root, "phase", name=phase.name)
            desc_elem = ET.SubElement(phase_elem, "description")
            desc_elem.text = phase.description

            for task in phase.tasks:
                task_attrib = {"id": task.id}
                if task.depends_on:
                    task_attrib["depends_on"] = ", ".join(task.depends_on)
                task_elem = ET.SubElement(phase_elem, "task", attrib=task_attrib)

                name_elem = ET.SubElement(task_elem, "name")
                name_elem.text = task.name

                files_elem = ET.SubElement(task_elem, "files")
                files_elem.text = (
                    "\n                " + "\n                ".join(task.files) + "\n            "
                )

                action_elem = ET.SubElement(task_elem, "action")
                action_elem.text = f"\n                {task.action}\n            "

                verify_elem = ET.SubElement(task_elem, "verify")
                verify_elem.text = f"\n                {task.verify}\n            "

                done_elem = ET.SubElement(task_elem, "done")
                done_elem.text = task.done

        ET.indent(root, space="    ")
        return ET.tostring(root, encoding="unicode")

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
