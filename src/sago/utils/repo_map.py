"""Aider-style repository map: extract class/function signatures from Python files."""

import ast
import os
from pathlib import Path

_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".planning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    "htmlcov",
}


def _format_arg(arg: ast.arg) -> str:
    """Format a function argument with optional type annotation."""
    name = arg.arg
    if arg.annotation:
        try:
            ann = ast.unparse(arg.annotation)
            return f"{name}: {ann}"
        except Exception:
            pass
    return name


def _format_function(node: ast.FunctionDef | ast.AsyncFunctionDef, indent: str = "") -> str:
    args = []
    for arg in node.args.args:
        args.append(_format_arg(arg))
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{indent}{prefix} {node.name}({', '.join(args)}){ret}"


def _format_class(node: ast.ClassDef) -> list[str]:
    bases = []
    for base in node.bases:
        try:
            bases.append(ast.unparse(base))
        except Exception:
            bases.append("?")
    base_str = f"({', '.join(bases)})" if bases else ""
    lines = [f"class {node.name}{base_str}:"]
    for item in node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            lines.append(_format_function(item, indent="    "))
    return lines


def _extract_signatures(source: str, filename: str) -> list[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    lines: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            lines.extend(_format_class(node))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            lines.append(_format_function(node))
    return lines


def generate_repo_map(
    project_path: Path,
    max_files: int = 100,
    max_chars: int = 8000,
) -> str:
    """Generate a compact repo map of Python file signatures.

    Walks .py files under project_path, extracts class/function signatures
    using AST, and returns a compact string representation.

    Args:
        project_path: Root directory to scan.
        max_files: Maximum number of .py files to process.
        max_chars: Truncate output at this character count.

    Returns:
        Compact string with file signatures, or empty string if nothing found.
    """
    output_parts: list[str] = []
    files_processed = 0

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [
            d for d in sorted(dirs) if d not in _SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            if files_processed >= max_files:
                break
            fpath = Path(root) / fname
            try:
                source = fpath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = fpath.relative_to(project_path)
            sigs = _extract_signatures(source, str(rel))
            if sigs:
                output_parts.append(f"{rel}:")
                for sig in sigs:
                    output_parts.append(f"  {sig}")
                output_parts.append("")
            files_processed += 1
        if files_processed >= max_files:
            break

    result = "\n".join(output_parts)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n... (truncated)"
    return result
