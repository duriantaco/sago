"""Tests for sago import command."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from sago.commands import app
from sago.commands.import_cmd import _gather_codebase_context, _walk_tree

runner = CliRunner()


@pytest.fixture
def existing_project(tmp_path: Path) -> Path:
    """Create a fake existing Python project to import."""
    # pyproject.toml
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "myapp"\nversion = "0.1.0"\n'
        'dependencies = ["flask>=2.0", "sqlalchemy"]\n'
    )
    # Source code
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (src / "main.py").write_text(
        "from flask import Flask\n\napp = Flask(__name__)\n\n"
        "@app.route('/')\ndef index() -> str:\n    return 'hello'\n"
    )
    (src / "models.py").write_text(
        "from sqlalchemy import Column, Integer, String\n\n"
        "class User:\n    id: int\n    name: str\n"
    )
    # README
    (tmp_path / "README.md").write_text("# MyApp\n\nA Flask web application.\n")
    # tests
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_placeholder():\n    pass\n")
    return tmp_path


class TestGatherCodebaseContext:
    def test_collects_repo_map(self, existing_project: Path) -> None:
        ctx = _gather_codebase_context(existing_project)
        assert "repo_map" in ctx
        assert "main.py" in ctx["repo_map"] or "models.py" in ctx["repo_map"]

    def test_collects_config_files(self, existing_project: Path) -> None:
        ctx = _gather_codebase_context(existing_project)
        assert "config_files" in ctx
        assert "pyproject.toml" in ctx["config_files"]
        assert "flask" in ctx["config_files"]

    def test_collects_readme(self, existing_project: Path) -> None:
        ctx = _gather_codebase_context(existing_project)
        assert "readme" in ctx
        assert "Flask web application" in ctx["readme"]

    def test_collects_directory_structure(self, existing_project: Path) -> None:
        ctx = _gather_codebase_context(existing_project)
        assert "directory_structure" in ctx
        assert "src/" in ctx["directory_structure"]

    def test_collects_environment(self, existing_project: Path) -> None:
        ctx = _gather_codebase_context(existing_project)
        assert "environment" in ctx
        assert "Python" in ctx["environment"]

    def test_skips_missing_configs(self, tmp_path: Path) -> None:
        """Empty directory still returns environment at minimum."""
        ctx = _gather_codebase_context(tmp_path)
        assert "environment" in ctx
        assert "config_files" not in ctx

    def test_truncates_large_config_files(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("x" * 10000)
        ctx = _gather_codebase_context(tmp_path)
        # Should be truncated to ~3000 chars
        toml_content = ctx["config_files"]
        assert len(toml_content) < 5000


class TestWalkTree:
    def test_respects_max_depth(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "file.txt").write_text("hi")
        lines: list[str] = []
        _walk_tree(tmp_path, lines, depth=0, max_depth=1)
        # Should not contain deeply nested file
        assert not any("file.txt" in line for line in lines)

    def test_skips_hidden_dirs(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "secret.txt").write_text("s")
        (tmp_path / "visible.txt").write_text("v")
        lines: list[str] = []
        _walk_tree(tmp_path, lines, depth=0, max_depth=2)
        assert not any(".hidden" in line for line in lines)
        assert any("visible.txt" in line for line in lines)

    def test_skips_venv(self, tmp_path: Path) -> None:
        (tmp_path / "venv").mkdir()
        (tmp_path / "venv" / "lib.py").write_text("x")
        lines: list[str] = []
        _walk_tree(tmp_path, lines, depth=0, max_depth=2)
        assert not any("venv" in line for line in lines)


class TestImportCommand:
    def test_help(self) -> None:
        result = runner.invoke(app, ["import", "--help"])
        assert result.exit_code == 0
        assert "existing codebase" in result.output.lower()

    @patch("sago.commands.import_cmd.load_config")
    @patch("sago.commands.import_cmd.check_llm_configured")
    @patch("sago.core.project.ProjectManager.generate_from_codebase", new_callable=AsyncMock)
    @patch("sago.core.project.ProjectManager.init_project")
    def test_import_creates_project_files(
        self,
        mock_init: AsyncMock,
        mock_generate: AsyncMock,
        mock_check_llm: AsyncMock,
        mock_load_config: AsyncMock,
        existing_project: Path,
    ) -> None:
        # Make generate_from_codebase write the expected files
        async def fake_generate(
            ctx: dict[str, str],
            path: Path,
            name: str,
            requirements_hint: str | None = None,
        ) -> None:
            (path / "PROJECT.md").write_text("# MyApp\n## Project Vision\nA web app\n")
            (path / "REQUIREMENTS.md").write_text("# Requirements\n* [ ] **REQ-1:** Add auth\n")

        mock_generate.side_effect = fake_generate

        result = runner.invoke(app, ["import", "--path", str(existing_project), "--yes"])
        assert result.exit_code == 0, result.output
        assert mock_generate.called
        # Check that codebase context was passed
        call_args = mock_generate.call_args
        codebase_ctx = call_args[0][0] if call_args[0] else call_args[1].get("codebase_context", {})
        assert isinstance(codebase_ctx, dict)

    @patch("sago.commands.import_cmd.load_config")
    @patch("sago.commands.import_cmd.check_llm_configured")
    @patch("sago.core.project.ProjectManager.generate_from_codebase", new_callable=AsyncMock)
    @patch("sago.core.project.ProjectManager.init_project")
    def test_import_passes_requirements_hint(
        self,
        mock_init: AsyncMock,
        mock_generate: AsyncMock,
        mock_check_llm: AsyncMock,
        mock_load_config: AsyncMock,
        existing_project: Path,
    ) -> None:
        async def fake_generate(
            ctx: dict[str, str],
            path: Path,
            name: str,
            requirements_hint: str | None = None,
        ) -> None:
            (path / "PROJECT.md").write_text("# Proj\n")
            (path / "REQUIREMENTS.md").write_text("# Reqs\n")

        mock_generate.side_effect = fake_generate

        result = runner.invoke(
            app,
            [
                "import",
                "--path",
                str(existing_project),
                "--yes",
                "-r",
                "add user authentication",
            ],
        )
        assert result.exit_code == 0, result.output
        # Verify hint was passed through
        call_kwargs = mock_generate.call_args
        # positional or keyword
        hint = (
            call_kwargs[1].get("requirements_hint")
            if "requirements_hint" in call_kwargs[1]
            else call_kwargs[0][3]
            if len(call_kwargs[0]) > 3
            else None
        )
        assert hint == "add user authentication"
