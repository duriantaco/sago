import logging
from pathlib import Path
from typing import Any

from sago.core.config import Config

logger = logging.getLogger(__name__)


class ProjectManager:
    TEMPLATE_FILES = [
        "PROJECT.md",
        "REQUIREMENTS.md",
        "STATE.md",
        "IMPORTANT.md",
        "CLAUDE.md",
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

        if project_path.exists() and not overwrite:
            existing_templates = [f for f in self.TEMPLATE_FILES if (project_path / f).exists()]
            if existing_templates:
                raise FileExistsError(
                    f"Project already exists at {project_path}. "
                    f"Found: {', '.join(existing_templates)}"
                )
        else:
            project_path.mkdir(parents=True, exist_ok=True)

        planning_dir = project_path / ".planning"
        planning_dir.mkdir(exist_ok=True)

        templates_dir = self.config.templates_dir
        template_vars = template_vars or {}
        template_vars.setdefault("project_name", project_name)

        for template_file in self.TEMPLATE_FILES:
            src = templates_dir / template_file
            dst = project_path / template_file

            if src.exists():
                content = src.read_text(encoding="utf-8")
                for key, value in template_vars.items():
                    placeholder = f"{{{{{key}}}}}"
                    content = content.replace(placeholder, str(value))

                dst.write_text(content, encoding="utf-8")

    async def generate_from_prompt(
        self,
        prompt: str,
        project_path: Path,
        project_name: str,
    ) -> None:
        """Generate PROJECT.md and REQUIREMENTS.md from a one-line prompt via LLM.

        Args:
            prompt: User's project description
            project_path: Path to the initialized project
            project_name: Name of the project

        Raises:
            ValueError: If the LLM response cannot be parsed into files
        """
        from sago.utils.llm import LLMClient

        client = LLMClient(
            model=self.config.llm_model,
            api_key=self.config.llm_api_key or None,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )

        system_prompt = (
            "You are a software architect. Given a project idea, produce two markdown files.\n"
            "Use exactly this format — no extra commentary:\n\n"
            "=== FILE: PROJECT.md ===\n"
            "(full PROJECT.md content)\n\n"
            "=== FILE: REQUIREMENTS.md ===\n"
            "(full REQUIREMENTS.md content)\n\n"
            "PROJECT.md must have: # <project name>, ## Project Vision, "
            "## Tech Stack & Constraints (bullet list), ## Core Architecture.\n"
            "REQUIREMENTS.md must have: # <project name> Requirements, "
            "## V1 Requirements (MVP) with * [ ] **REQ-N:** format."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Project name: {project_name}\nIdea: {prompt}",
            },
        ]

        response = client.chat_completion(messages)
        content = response["content"]

        generated = self._parse_generated_files(content)

        for filename, file_content in generated.items():
            (project_path / filename).write_text(file_content, encoding="utf-8")
            logger.info(f"Wrote generated {filename} ({len(file_content)} chars)")

    @staticmethod
    def _parse_generated_files(content: str) -> dict[str, str]:
        files: dict[str, str] = {}
        expected = {"PROJECT.md", "REQUIREMENTS.md"}

        parts = content.split("=== FILE: ")
        for part in parts[1:]:  # skip text before first marker
            header, _, body = part.partition("===")
            filename = header.strip()
            if filename in expected:
                files[filename] = body.strip() + "\n"

        missing = expected - set(files.keys())
        if missing:
            raise ValueError(f"LLM output missing expected files: {', '.join(sorted(missing))}")

        return files

    def read_file(self, project_path: Path, filename: str) -> str:
        file_path = Path(project_path) / filename
        return file_path.read_text(encoding="utf-8")

    def write_file(self, project_path: Path, filename: str, content: str) -> None:
        file_path = Path(project_path) / filename
        file_path.write_text(content, encoding="utf-8")

    def update_file(self, project_path: Path, filename: str, updates: dict[str, str]) -> None:
        content = self.read_file(project_path, filename)

        for search, replace in updates.items():
            content = content.replace(search, replace)

        self.write_file(project_path, filename, content)

    def get_project_info(self, project_path: Path) -> dict[str, Any]:
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
        project_path = Path(project_path)
        if not project_path.exists():
            return False

        required_files = ["PROJECT.md", "REQUIREMENTS.md"]
        return any((project_path / f).exists() for f in required_files)
