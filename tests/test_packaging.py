import tomllib
from pathlib import Path


def test_pyproject_packages_mission_control_html() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    package_data = data["tool"]["setuptools"]["package-data"]["sago"]

    assert "web/mission_control.html" in package_data
    assert "web/dashboard.html" not in package_data
