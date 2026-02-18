import os
import platform
import subprocess
import sys
from functools import wraps
from typing import Any, Callable, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def is_admin() -> bool:

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def requires_elevation() -> Callable[[F], F]:

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if is_admin():
                return func(*args, **kwargs)
            else:
                from rich.console import Console

                console = Console()
                console.print(
                    "[yellow]⚠️  This operation requires administrator/root privileges.[/yellow]"
                )
                console.print(
                    "[yellow]Please run with sudo (Unix) or as Administrator (Windows).[/yellow]"
                )

                raise PermissionError(
                    "Administrative privileges required. "
                    f"Please run with {'sudo' if platform.system() != 'Windows' else 'Administrator rights'}."
                )

        return cast(F, wrapper)

    return decorator


def re_exec_with_sudo() -> int:

    system = platform.system()

    if is_admin():
        return 0

    if system == "Windows":
        return _windows_elevate()
    else:
        return _unix_elevate()


def _unix_elevate() -> int:

    cmd = ["sudo", sys.executable] + sys.argv

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        raise RuntimeError("Elevation cancelled by user") from None
    except Exception as e:
        raise RuntimeError(f"Failed to elevate: {e}") from e


def _windows_elevate() -> int:
    try:
        return _do_windows_elevate()
    except Exception as e:
        if "cancelled" in str(e).lower():
            raise RuntimeError("Elevation cancelled by user") from e
        raise RuntimeError(f"Failed to elevate on Windows: {e}") from e


def _do_windows_elevate() -> int:
    import ctypes

    script = sys.argv[0]
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])

    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        f'"{script}" {params}', None, 1,
    )

    if ret <= 32:
        error_codes = {
            0: "Out of memory",
            2: "File not found",
            3: "Path not found",
            5: "Access denied (UAC cancelled)",
            26: "Sharing violation",
            27: "File association broken",
            31: "No association",
        }
        error_msg = error_codes.get(ret, f"Unknown error (code {ret})")
        raise RuntimeError(f"Elevation failed: {error_msg}")

    sys.exit(0)


def run_with_elevation(command: list[str], check: bool = True) -> subprocess.CompletedProcess:

    system = platform.system()

    if is_admin():
        return subprocess.run(command, check=check, capture_output=True, text=True)

    if system != "Windows":
        command = ["sudo"] + command

    try:
        return subprocess.run(command, check=check, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == 1 and "sudo" in str(e):
            raise PermissionError("Sudo authentication failed or cancelled") from e
        raise
    except Exception as e:
        raise PermissionError(f"Failed to run command with elevation: {e}") from e


def check_elevation_available() -> tuple[bool, str]:

    if is_admin():
        return True, "already_elevated"

    system = platform.system()

    if system == "Windows":
        try:
            import ctypes

            return True, "UAC"
        except Exception:
            return False, "none"
    else:
        try:
            result = subprocess.run(
                ["which", "sudo"],
                capture_output=True,
                check=False,
                timeout=1,
            )
            if result.returncode == 0:
                return True, "sudo"
        except Exception:
            pass

        return False, "none"
