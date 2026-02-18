"""Tests for privilege elevation utilities."""

import platform
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sago.utils.elevation import (
    check_elevation_available,
    is_admin,
    requires_elevation,
    run_with_elevation,
)


def test_is_admin() -> None:
    """Test checking if process has admin privileges."""
    # We can't really test this fully without actually running as admin
    # Just verify it returns a boolean
    result = is_admin()
    assert isinstance(result, bool)


@patch("sago.utils.elevation.is_admin")
def test_requires_elevation_decorator_when_admin(mock_is_admin: MagicMock) -> None:
    """Test that decorator allows execution when already admin."""
    mock_is_admin.return_value = True

    @requires_elevation()
    def test_func() -> str:
        return "success"

    result = test_func()
    assert result == "success"


@patch("sago.utils.elevation.is_admin")
def test_requires_elevation_decorator_when_not_admin(mock_is_admin: MagicMock) -> None:
    """Test that decorator raises error when not admin."""
    mock_is_admin.return_value = False

    @requires_elevation()
    def test_func() -> str:
        return "success"

    with pytest.raises(PermissionError, match="Administrative privileges required"):
        test_func()


def test_detects_elevation_needed() -> None:
    """Test detecting if elevation is needed."""
    available, method = check_elevation_available()

    assert isinstance(available, bool)
    assert isinstance(method, str)
    assert method in ["already_elevated", "sudo", "UAC", "none"]


@patch("sago.utils.elevation.is_admin")
@patch("subprocess.run")
def test_run_with_elevation_when_admin(
    mock_run: MagicMock, mock_is_admin: MagicMock
) -> None:
    """Test running command when already admin."""
    mock_is_admin.return_value = True
    mock_run.return_value = subprocess.CompletedProcess(
        args=["echo", "test"], returncode=0, stdout="test", stderr=""
    )

    result = run_with_elevation(["echo", "test"])

    assert result.returncode == 0
    # Should not add sudo when already admin
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert "sudo" not in call_args


@patch("sago.utils.elevation.is_admin")
@patch("sago.utils.elevation.platform.system")
@patch("subprocess.run")
def test_run_with_elevation_adds_sudo_on_unix(
    mock_run: MagicMock, mock_system: MagicMock, mock_is_admin: MagicMock
) -> None:
    """Test that sudo is added on Unix systems when not admin."""
    mock_is_admin.return_value = False
    mock_system.return_value = "Linux"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["sudo", "echo", "test"], returncode=0, stdout="test", stderr=""
    )

    result = run_with_elevation(["echo", "test"])

    assert result.returncode == 0
    # Should add sudo prefix
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "sudo"
    assert "echo" in call_args


@patch("sago.utils.elevation.is_admin")
def test_check_elevation_when_already_elevated(mock_is_admin: MagicMock) -> None:
    """Test elevation check when already elevated."""
    mock_is_admin.return_value = True

    available, method = check_elevation_available()

    assert available is True
    assert method == "already_elevated"


@patch("sago.utils.elevation.is_admin")
@patch("sago.utils.elevation.platform.system")
@patch("subprocess.run")
def test_check_elevation_sudo_available(
    mock_run: MagicMock, mock_system: MagicMock, mock_is_admin: MagicMock
) -> None:
    """Test elevation check when sudo is available."""
    mock_is_admin.return_value = False
    mock_system.return_value = "Linux"
    mock_run.return_value = subprocess.CompletedProcess(
        args=["which", "sudo"], returncode=0, stdout="/usr/bin/sudo", stderr=""
    )

    available, method = check_elevation_available()

    assert available is True
    assert method == "sudo"


@patch("sago.utils.elevation.is_admin")
@patch("subprocess.run")
def test_run_with_elevation_command_failure(
    mock_run: MagicMock, mock_is_admin: MagicMock
) -> None:
    """Test handling of command failure."""
    mock_is_admin.return_value = True
    mock_run.side_effect = subprocess.CalledProcessError(1, ["false"])

    with pytest.raises(subprocess.CalledProcessError):
        run_with_elevation(["false"], check=True)


@patch("sago.utils.elevation.is_admin")
@patch("subprocess.run")
def test_run_with_elevation_no_check(
    mock_run: MagicMock, mock_is_admin: MagicMock
) -> None:
    """Test running command without check."""
    mock_is_admin.return_value = True
    mock_run.return_value = subprocess.CompletedProcess(
        args=["false"], returncode=1, stdout="", stderr="error"
    )

    # Should not raise even though returncode is 1
    result = run_with_elevation(["false"], check=False)
    assert result.returncode == 1
