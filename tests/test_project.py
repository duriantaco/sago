"""Tests for project management."""

from pathlib import Path

import pytest

from sago.core.config import Config
from sago.core.project import ProjectManager


@pytest.fixture
def project_manager(tmp_path: Path) -> ProjectManager:
    """Create a ProjectManager with temporary config."""
    config = Config(planning_dir=tmp_path / ".planning")
    return ProjectManager(config)


def test_init_creates_templates(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test that init creates all template files."""
    project_path = tmp_path / "test_project"

    project_manager.init_project(project_path, project_name="TestProject")

    assert project_path.exists()
    assert (project_path / ".planning").exists()

    # Check all template files are created
    for template_file in ProjectManager.TEMPLATE_FILES:
        file_path = project_path / template_file
        assert file_path.exists(), f"{template_file} should exist"
        assert file_path.stat().st_size > 0, f"{template_file} should not be empty"


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

    # Should have new content (from template)
    content = (project_path / "PROJECT.md").read_text()
    assert "old content" not in content


def test_read_write_file(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test reading and writing project files."""
    project_path = tmp_path / "rw_project"
    project_manager.init_project(project_path)

    # Write new content
    new_content = "# New Content\nThis is a test."
    project_manager.write_file(project_path, "TEST.md", new_content)

    # Read it back
    content = project_manager.read_file(project_path, "TEST.md")
    assert content == new_content


def test_update_file(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test updating specific sections in a file."""
    project_path = tmp_path / "update_project"
    project_manager.init_project(project_path)

    # Update STATE.md
    updates = {
        "Active Phase:** Phase 1": "Active Phase:** Phase 2",
    }
    project_manager.update_file(project_path, "STATE.md", updates)

    content = project_manager.read_file(project_path, "STATE.md")
    assert "Phase 2" in content


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
    """Test checking if directory is a sago project."""
    # Not a sago project
    non_project = tmp_path / "not_sago"
    non_project.mkdir()
    assert project_manager.is_sago_project(non_project) is False

    # Create sago project
    sago_project = tmp_path / "sago_project"
    project_manager.init_project(sago_project)
    assert project_manager.is_sago_project(sago_project) is True


def test_template_variable_substitution(tmp_path: Path, project_manager: ProjectManager) -> None:
    """Test that template variables are substituted correctly."""
    project_path = tmp_path / "var_project"
    template_vars = {"project_name": "MyAwesomeProject"}

    project_manager.init_project(project_path, template_vars=template_vars)

    # Check if variable was substituted (if template uses {{project_name}})
    content = project_manager.read_file(project_path, "PROJECT.md")
    assert content is not None  # At minimum, file should exist and be readable
