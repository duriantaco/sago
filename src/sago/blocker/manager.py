import platform
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


class HostsManager:

    def __init__(self, hosts_file_path: Path | None = None) -> None:
        if hosts_file_path is None:
            hosts_file_path = self._get_default_hosts_path()

        self.hosts_file = Path(hosts_file_path)
        self.backup_file = self.hosts_file.with_suffix(".bak")
        self.marker_start = "# sago BLOCKED SITES - START"
        self.marker_end = "# sago BLOCKED SITES - END"

    def _get_default_hosts_path(self) -> Path:
        system = platform.system()
        if system == "Windows":
            return Path(r"C:\Windows\System32\drivers\etc\hosts")
        else:
            return Path("/etc/hosts")

    def _remove_sago_block(self, content: str) -> str:
        if self.marker_start not in content:
            return content

        lines = content.split("\n")
        new_lines = []
        skip = False

        for line in lines:
            if self.marker_start in line:
                skip = True
                continue
            if self.marker_end in line:
                skip = False
                continue
            if not skip:
                new_lines.append(line)

        return "\n".join(new_lines)

    def read_hosts(self) -> str:
        try:
            return self.hosts_file.read_text(encoding="utf-8")
        except PermissionError as e:
            raise PermissionError(
                f"Cannot read hosts file at {self.hosts_file}. "
                "Try running with sudo/administrator privileges."
            ) from e
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Hosts file not found at {self.hosts_file}") from e

    def backup_hosts(self) -> Path:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.hosts_file.parent / f"hosts.{timestamp}.bak"

            shutil.copy2(self.hosts_file, backup_file)
            return backup_file
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create backup at {backup_file}. "
                "Try running with sudo/administrator privileges."
            ) from e

    def get_blocked_domains(self) -> list[str]:
        try:
            content = self.read_hosts()
        except (PermissionError, FileNotFoundError):
            return []

        blocked: list[str] = []

        if self.marker_start not in content:
            return blocked

        lines = content.split("\n")
        in_block = False

        for line in lines:
            if self.marker_start in line:
                in_block = True
                continue
            if self.marker_end in line:
                break

            if in_block:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1"):
                        blocked.append(parts[1])

        return blocked

    def is_blocked(self, domain: str) -> bool:
        return domain in self.get_blocked_domains()

    def block_sites(self, domains: list[str]) -> None:
        if not domains:
            raise ValueError("Must provide at least one domain to block")

        domains = list(set(d.strip().lower() for d in domains if d.strip()))
        self.backup_hosts()
        content = self._build_block_content(domains)
        self._write_hosts(content)

    def _build_block_content(self, domains: list[str]) -> str:
        content = self.read_hosts()
        currently_blocked = self.get_blocked_domains()

        all_blocked = sorted(set(currently_blocked + domains))
        content = self._remove_sago_block(content)

        if not content.endswith("\n"):
            content += "\n"

        content += f"\n{self.marker_start}\n"
        content += f"# Added by sago on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        for domain in all_blocked:
            content += f"0.0.0.0 {domain}\n"
            if not domain.startswith("www."):
                content += f"0.0.0.0 www.{domain}\n"
        content += f"{self.marker_end}\n"
        return content

    def _write_hosts(self, content: str) -> None:
        try:
            self.hosts_file.write_text(content, encoding="utf-8")
        except PermissionError as e:
            raise PermissionError(
                f"Cannot modify hosts file at {self.hosts_file}. "
                "Try running with sudo/administrator privileges."
            ) from e

    def unblock_sites(self, domains: list[str] | None = None) -> None:
        self.backup_hosts()
        content = self._build_unblock_content(domains)
        if content is not None:
            self._write_hosts(content)

    def _build_unblock_content(self, domains: list[str] | None) -> str | None:
        content = self.read_hosts()

        if self.marker_start not in content:
            return None

        if domains is None:
            return self._remove_sago_block(content)

        domains = list(set(d.strip().lower() for d in domains if d.strip()))
        currently_blocked = self.get_blocked_domains()
        remaining = [
            d for d in currently_blocked
            if d not in domains and not any(d == f"www.{dom}" for dom in domains)
        ]

        content = self._remove_sago_block(content)

        if remaining:
            if not content.endswith("\n"):
                content += "\n"

            content += f"\n{self.marker_start}\n"
            content += (
                f"# Updated by sago on "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            for domain in remaining:
                content += f"0.0.0.0 {domain}\n"
            content += f"{self.marker_end}\n"

        return content

    def get_info(self) -> dict[str, Any]:
        return {
            "hosts_file": str(self.hosts_file),
            "exists": self.hosts_file.exists(),
            "readable": self._check_readable(),
            "writable": self._check_writable(),
            "blocked_count": len(self.get_blocked_domains()),
            "blocked_domains": self.get_blocked_domains(),
        }

    def _check_readable(self) -> bool:
        try:
            self.read_hosts()
            return True
        except (PermissionError, FileNotFoundError):
            return False

    def _check_writable(self) -> bool:
        return self.hosts_file.exists() and (
            platform.system() == "Windows" or self.hosts_file.stat().st_mode & 0o200
        )
