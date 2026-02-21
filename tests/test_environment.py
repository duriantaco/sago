import sys

from sago.utils.environment import (
    PYPROJECT_TEMPLATE,
    detect_environment,
    format_environment_context,
)


def test_detect_environment_keys() -> None:
    env = detect_environment()
    assert set(env.keys()) == {
        "python_version",
        "python_full_version",
        "os",
        "platform",
        "architecture",
    }


def test_detect_environment_types() -> None:
    env = detect_environment()
    for value in env.values():
        assert isinstance(value, str)
        assert len(value) > 0


def test_detect_environment_python_version() -> None:
    env = detect_environment()
    expected = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert env["python_version"] == expected
    expected_full = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    assert env["python_full_version"] == expected_full


def test_format_environment_context() -> None:
    env = {
        "python_version": "3.13",
        "python_full_version": "3.13.1",
        "os": "Linux",
        "platform": "x86_64",
        "architecture": "64bit",
    }
    result = format_environment_context(env)
    assert "Python: 3.13.1" in result
    assert "OS: Linux" in result
    assert "Platform: x86_64" in result
    assert "Architecture: 64bit" in result


def test_pyproject_template_substitution() -> None:
    filled = PYPROJECT_TEMPLATE.replace("{python_version}", "3.12")
    assert '">=' in filled
    assert ">=3.12" in filled
    assert "{python_version}" not in filled


def test_pyproject_template_has_pep621_structure() -> None:
    assert "[build-system]" in PYPROJECT_TEMPLATE
    assert "[project]" in PYPROJECT_TEMPLATE
    assert "setuptools" in PYPROJECT_TEMPLATE
    assert "[tool.poetry" not in PYPROJECT_TEMPLATE
