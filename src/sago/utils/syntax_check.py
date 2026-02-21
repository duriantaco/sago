"""Syntax checking for generated Python files using ast.parse()."""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SyntaxCheckResult:
    success: bool
    errors: dict[str, str] = field(default_factory=dict)


def check_python_syntax(files: dict[str, str], project_path: Path) -> SyntaxCheckResult:
    errors: dict[str, str] = {}
    for file_path_str, content in files.items():
        if not file_path_str.endswith(".py"):
            continue
        try:
            ast.parse(content, filename=file_path_str)
        except SyntaxError as e:
            line_info = f" (line {e.lineno})" if e.lineno else ""
            errors[file_path_str] = f"{e.msg}{line_info}"
    return SyntaxCheckResult(success=len(errors) == 0, errors=errors)
