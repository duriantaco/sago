from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sago.core.config import Config
from sago.core.project import ProjectManager


@pytest.fixture
def project_manager(tmp_path: Path) -> ProjectManager:
    """Create a ProjectManager with temporary config."""
    config = Config(planning_dir=tmp_path / ".planning")
    return ProjectManager(config)


def test_init_creates_templates(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test that init creates exactly 4 template files."""
    project_path = tmp_path / "test_project"

    project_manager.init_project(project_path, project_name="TestProject")

    assert project_path.exists()
    assert (project_path / ".planning").exists()

    # Check all 4 template files are created
    for template_file in ProjectManager.TEMPLATE_FILES:
        file_path = project_path / template_file
        assert file_path.exists(), f"{template_file} should exist"
        assert file_path.stat().st_size > 0, f"{template_file} should not be empty"

    # Check dropped files do NOT exist
    for dropped in ["ROADMAP.md", "SUMMARY.md"]:
        assert not (project_path / dropped).exists(), f"{dropped} should not exist"


def test_init_with_existing_project(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test that init raises error if project exists."""
    project_path = tmp_path / "existing_project"
    project_path.mkdir()
    (project_path / "PROJECT.md").write_text("existing content")

    with pytest.raises(FileExistsError):
        project_manager.init_project(project_path)


def test_init_with_overwrite(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test that init can overwrite existing files."""
    project_path = tmp_path / "overwrite_project"
    project_path.mkdir()
    (project_path / "PROJECT.md").write_text("old content")

    project_manager.init_project(project_path, overwrite=True)

    content = (project_path / "PROJECT.md").read_text()
    assert "old content" not in content


def test_read_write_file(tmp_path: Path, project_manager: ProjectManager) -> None:
    project_path = tmp_path / "rw_project"
    project_manager.init_project(project_path)

    new_content = "# New Content\nThis is a test."
    project_manager.write_file(project_path, "TEST.md", new_content)

    content = project_manager.read_file(project_path, "TEST.md")
    assert content == new_content


def test_update_file(tmp_path: Path, project_manager: ProjectManager) -> None:
    project_path = tmp_path / "update_project"
    project_manager.init_project(project_path)

    updates = {
        "Active Phase:** Not started": "Active Phase:** Phase 1",
    }
    project_manager.update_file(project_path, "STATE.md", updates)

    content = project_manager.read_file(project_path, "STATE.md")
    assert "Phase 1" in content


def test_get_project_info(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test getting project information."""
    project_path = tmp_path / "info_project"
    project_manager.init_project(project_path)

    info = project_manager.get_project_info(project_path)

    assert info["exists"] is True
    assert info["has_planning_dir"] is True
    assert info["name"] == "info_project"
    assert all(info["template_files"].values())


def test_is_sago_project(tmp_path: Path, project_manager: ProjectManager) -> None:
    non_project = tmp_path / "not_sago"
    non_project.mkdir()
    assert project_manager.is_sago_project(non_project) is False

    sago_project = tmp_path / "sago_project"
    project_manager.init_project(sago_project)
    assert project_manager.is_sago_project(sago_project) is True


def test_template_variable_substitution(tmp_path: Path, project_manager: ProjectManager) -> None:
    project_path = tmp_path / "var_project"
    template_vars = {"project_name": "MyAwesomeProject"}

    project_manager.init_project(project_path, template_vars=template_vars)

    content = project_manager.read_file(project_path, "PROJECT.md")
    assert "{{project_name}}" not in content
    assert "MyAwesomeProject" in content


@pytest.mark.asyncio
async def test_generate_from_prompt(tmp_path: Path, project_manager: ProjectManager) -> None:
    project_path = tmp_path / "prompt_project"
    project_manager.init_project(project_path, project_name="todo-app")

    fake_response = {
        "content": (
            "=== FILE: PROJECT.md ===\n"
            "# todo-app\n\n## Project Vision\nA simple todo app.\n\n"
            "## Tech Stack & Constraints\n* **Language:** Python\n\n"
            "## Core Architecture\nCLI app.\n\n"
            "=== FILE: REQUIREMENTS.md ===\n"
            "# todo-app Requirements\n\n## V1 Requirements (MVP)\n"
            "* [ ] **REQ-1:** Add todos\n"
        ),
        "usage": {"total_tokens": 100},
        "finish_reason": "stop",
        "model": "test",
    }

    with patch("sago.utils.llm.LLMClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat_completion.return_value = fake_response
        mock_cls.return_value = mock_client

        await project_manager.generate_from_prompt("A todo app", project_path, "todo-app")

    project_md = (project_path / "PROJECT.md").read_text()
    assert "todo-app" in project_md
    assert "Project Vision" in project_md

    req_md = (project_path / "REQUIREMENTS.md").read_text()
    assert "REQ-1" in req_md


@pytest.mark.asyncio
async def test_generate_from_prompt_parse_error(
    tmp_path: Path, project_manager: ProjectManager
) -> None:
    project_path = tmp_path / "bad_prompt_project"
    project_manager.init_project(project_path, project_name="bad-project")

    fake_response = {
        "content": "Here is your project plan without any file markers.",
        "usage": {"total_tokens": 50},
        "finish_reason": "stop",
        "model": "test",
    }

    with patch("sago.utils.llm.LLMClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat_completion.return_value = fake_response
        mock_cls.return_value = mock_client

        with pytest.raises(ValueError, match="missing expected files"):
            await project_manager.generate_from_prompt("bad prompt", project_path, "bad-project")
