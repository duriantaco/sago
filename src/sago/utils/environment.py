import platform
import sys


def detect_environment() -> dict[str, str]:
    ver = sys.version_info
    return {
        "python_version": f"{ver.major}.{ver.minor}",
        "python_full_version": f"{ver.major}.{ver.minor}.{ver.micro}",
        "os": platform.system(),
        "platform": platform.machine(),
        "architecture": platform.architecture()[0],
    }


def format_environment_context(env: dict[str, str]) -> str:
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
