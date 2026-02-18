from pathlib import Path
from typing import Any

from sago.core.config import Config


class ProjectManager:

    TEMPLATE_FILES = [
        "PROJECT.md",
        "REQUIREMENTS.md",
        "ROADMAP.md",
        "STATE.md",
        "PLAN.md",
        "SUMMARY.md",
        "IMPORTANT.md",
    ]

    def __init__(self, config: Config | None = None) -> None:
        """Initialize ProjectManager.

        Args:
            config: Configuration instance. If None, creates default config.
        """
        self.config = config or Config()

    def init_project(
        self,
        project_path: Path,
        project_name: str | None = None,
        overwrite: bool = False,
        template_vars: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a new project with sago templates.

        Args:
            project_path: Path where project should be created
            project_name: Name of the project (defaults to directory name)
            overwrite: Whether to overwrite existing files
            template_vars: Variables to substitute in templates

        Raises:
            FileExistsError: If project directory exists and overwrite is False
        """
        project_path = Path(project_path).resolve()
        project_name = project_name or project_path.name

        # Create project directory
        if project_path.exists() and not overwrite:
            # Check if any template files exist
            existing_templates = [
                f for f in self.TEMPLATE_FILES if (project_path / f).exists()
            ]
            if existing_templates:
                raise FileExistsError(
                    f"Project already exists at {project_path}. "
                    f"Found: {', '.join(existing_templates)}"
                )
        else:
            project_path.mkdir(parents=True, exist_ok=True)

        # Create .planning directory
        planning_dir = project_path / ".planning"
        planning_dir.mkdir(exist_ok=True)

        # Copy template files
        templates_dir = self.config.templates_dir
        template_vars = template_vars or {}
        template_vars.setdefault("project_name", project_name)

        for template_file in self.TEMPLATE_FILES:
            src = templates_dir / template_file
            dst = project_path / template_file

            if src.exists():
                # Read template content
                content = src.read_text(encoding="utf-8")

                # Simple variable substitution
                for key, value in template_vars.items():
                    placeholder = f"{{{{{key}}}}}"
                    content = content.replace(placeholder, str(value))

                # Write to destination
                dst.write_text(content, encoding="utf-8")

    def read_file(self, project_path: Path, filename: str) -> str:
        """Read a project file.

        Args:
            project_path: Path to project directory
            filename: Name of file to read

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = Path(project_path) / filename
        return file_path.read_text(encoding="utf-8")

    def write_file(self, project_path: Path, filename: str, content: str) -> None:
        """Write content to a project file.

        Args:
            project_path: Path to project directory
            filename: Name of file to write
            content: Content to write
        """
        file_path = Path(project_path) / filename
        file_path.write_text(content, encoding="utf-8")

    def update_file(
        self, project_path: Path, filename: str, updates: dict[str, str]
    ) -> None:
        """Update specific sections in a project file.

        Args:
            project_path: Path to project directory
            filename: Name of file to update
            updates: Dictionary of {search_string: replacement_string}
        """
        content = self.read_file(project_path, filename)

        for search, replace in updates.items():
            content = content.replace(search, replace)

        self.write_file(project_path, filename, content)

    def get_project_info(self, project_path: Path) -> dict[str, Any]:
        """Get information about a project.

        Args:
            project_path: Path to project directory

        Returns:
            Dictionary with project information
        """
        project_path = Path(project_path)
        info: dict[str, Any] = {
            "path": str(project_path),
            "name": project_path.name,
            "exists": project_path.exists(),
            "has_planning_dir": (project_path / ".planning").exists(),
            "template_files": {},
        }

        for template_file in self.TEMPLATE_FILES:
            file_path = project_path / template_file
            info["template_files"][template_file] = file_path.exists()

        return info

    def is_sago_project(self, project_path: Path) -> bool:
        """Check if a directory is a sago project.

        Args:
            project_path: Path to check

        Returns:
            True if directory contains sago template files
        """
        project_path = Path(project_path)
        if not project_path.exists():
            return False

        # A sago project should have at least PROJECT.md or REQUIREMENTS.md
        # PLAN.md can be generated, so it's not required
        required_files = ["PROJECT.md", "REQUIREMENTS.md"]
        return any((project_path / f).exists() for f in required_files)
