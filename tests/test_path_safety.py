"""Tests for path traversal protection."""

from pathlib import Path

import pytest

from sago.utils.paths import safe_resolve


def test_safe_resolve_normal_relative(tmp_path: Path) -> None:
    result = safe_resolve(tmp_path, "src/main.py")
    assert result == (tmp_path / "src" / "main.py").resolve()


def test_safe_resolve_nested(tmp_path: Path) -> None:
    result = safe_resolve(tmp_path, "a/b/c/d.txt")
    assert result.is_relative_to(tmp_path.resolve())


def test_safe_resolve_blocks_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Path traversal blocked"):
        safe_resolve(tmp_path, "../../../etc/passwd")


def test_safe_resolve_blocks_double_dot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Path traversal blocked"):
        safe_resolve(tmp_path, "src/../../outside.txt")


def test_safe_resolve_blocks_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Path traversal blocked"):
        safe_resolve(tmp_path, "/etc/passwd")


def test_safe_resolve_dot_current_dir(tmp_path: Path) -> None:
    result = safe_resolve(tmp_path, "./file.txt")
    assert result == (tmp_path / "file.txt").resolve()


def test_safe_resolve_empty_relative(tmp_path: Path) -> None:
    result = safe_resolve(tmp_path, "")
    assert result == tmp_path.resolve()
