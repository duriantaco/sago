"""Path safety utilities for preventing traversal attacks."""

from pathlib import Path


def safe_resolve(project_path: Path, relative: str) -> Path:
    """Resolve a relative path, ensuring it stays within project_path.

    Args:
        project_path: The root project directory.
        relative: A relative file path (e.g. from LLM output).

    Returns:
        The resolved absolute Path.

    Raises:
        ValueError: If the resolved path escapes project_path.
    """
    resolved = (project_path / relative).resolve()
    if not resolved.is_relative_to(project_path.resolve()):
        raise ValueError(f"Path traversal blocked: {relative!r}")
    return resolved
