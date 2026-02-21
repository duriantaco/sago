"""Detect runtime environment (Python version, OS, platform) for LLM context."""

import platform
import sys


def detect_environment() -> dict[str, str]:
    """Return runtime environment details.

    Returns a dict with keys:
        python_version: e.g. "3.13"
        python_full_version: e.g. "3.13.1"
        os: e.g. "Darwin", "Linux", "Windows"
        platform: e.g. "arm64", "x86_64"
        architecture: e.g. "64bit"
    """
    ver = sys.version_info
    return {
        "python_version": f"{ver.major}.{ver.minor}",
        "python_full_version": f"{ver.major}.{ver.minor}.{ver.micro}",
        "os": platform.system(),
        "platform": platform.machine(),
        "architecture": platform.architecture()[0],
    }


def format_environment_context(env: dict[str, str]) -> str:
    """Format environment dict into a text block for LLM prompts."""
    return (
        f"Python: {env['python_full_version']}\n"
        f"OS: {env['os']}\n"
        f"Platform: {env['platform']}\n"
        f"Architecture: {env['architecture']}"
    )


PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "<project-name>"
version = "0.1.0"
requires-python = ">={python_version}"
dependencies = [
    # "flask>=2.0",
]

[tool.setuptools.packages.find]
where = ["src"]
"""
