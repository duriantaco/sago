"""Tests for hosts file blocker."""

from pathlib import Path

import pytest

from sago.blocker.manager import HostsManager


@pytest.fixture
def temp_hosts(tmp_path: Path) -> Path:
    """Create a temporary hosts file for testing."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text(
        "# Test hosts file\n127.0.0.1 localhost\n::1 localhost\n", encoding="utf-8"
    )
    return hosts_file


def test_hosts_manager_reads(temp_hosts: Path) -> None:
    """Test that HostsManager can read hosts file."""
    manager = HostsManager(temp_hosts)
    content = manager.read_hosts()

    assert "127.0.0.1 localhost" in content
    assert "Test hosts file" in content


def test_backup_creates_file(temp_hosts: Path) -> None:
    """Test that backup creates a backup file."""
    manager = HostsManager(temp_hosts)
    backup_path = manager.backup_hosts()

    assert backup_path.exists()
    assert backup_path.name.startswith("hosts.")
    assert backup_path.name.endswith(".bak")

    # Backup should have same content as original
    assert backup_path.read_text() == temp_hosts.read_text()


def test_block_sites_adds_domains(temp_hosts: Path) -> None:
    """Test that block_sites adds domains to hosts file."""
    manager = HostsManager(temp_hosts)

    domains = ["example.com", "test.com"]
    manager.block_sites(domains)

    content = temp_hosts.read_text()

    assert "sago BLOCKED SITES - START" in content
    assert "0.0.0.0 example.com" in content
    assert "0.0.0.0 test.com" in content
    assert "sago BLOCKED SITES - END" in content


def test_block_sites_includes_www(temp_hosts: Path) -> None:
    """Test that block_sites also blocks www variant."""
    manager = HostsManager(temp_hosts)

    manager.block_sites(["example.com"])

    content = temp_hosts.read_text()

    assert "0.0.0.0 example.com" in content
    assert "0.0.0.0 www.example.com" in content


def test_get_blocked_domains(temp_hosts: Path) -> None:
    """Test getting list of blocked domains."""
    manager = HostsManager(temp_hosts)

    # Initially empty
    assert manager.get_blocked_domains() == []

    # After blocking
    manager.block_sites(["example.com", "test.com"])
    blocked = manager.get_blocked_domains()

    assert "example.com" in blocked
    assert "www.example.com" in blocked
    assert "test.com" in blocked


def test_is_blocked(temp_hosts: Path) -> None:
    """Test checking if a domain is blocked."""
    manager = HostsManager(temp_hosts)

    assert manager.is_blocked("example.com") is False

    manager.block_sites(["example.com"])

    assert manager.is_blocked("example.com") is True
    assert manager.is_blocked("www.example.com") is True
    assert manager.is_blocked("other.com") is False


def test_unblock_sites_specific(temp_hosts: Path) -> None:
    """Test unblocking specific domains."""
    manager = HostsManager(temp_hosts)

    # Block multiple sites
    manager.block_sites(["example.com", "test.com", "blocked.com"])

    # Unblock one
    manager.unblock_sites(["example.com"])

    blocked = manager.get_blocked_domains()
    assert "example.com" not in blocked
    assert "www.example.com" not in blocked
    assert "test.com" in blocked
    assert "blocked.com" in blocked


def test_unblock_sites_all(temp_hosts: Path) -> None:
    """Test unblocking all domains."""
    manager = HostsManager(temp_hosts)

    # Block sites
    manager.block_sites(["example.com", "test.com"])

    # Unblock all
    manager.unblock_sites(None)

    # Should be empty
    assert manager.get_blocked_domains() == []

    # Markers should be removed
    content = temp_hosts.read_text()
    assert "sago BLOCKED SITES" not in content


def test_block_sites_preserves_original_content(temp_hosts: Path) -> None:
    """Test that blocking preserves original hosts file content."""
    original_content = temp_hosts.read_text()

    manager = HostsManager(temp_hosts)
    manager.block_sites(["example.com"])

    new_content = temp_hosts.read_text()

    # Original content should still be present
    assert "127.0.0.1 localhost" in new_content
    assert "::1 localhost" in new_content


def test_block_sites_empty_list(temp_hosts: Path) -> None:
    """Test that blocking empty list raises error."""
    manager = HostsManager(temp_hosts)

    with pytest.raises(ValueError, match="Must provide at least one domain"):
        manager.block_sites([])


def test_block_sites_deduplicates(temp_hosts: Path) -> None:
    """Test that blocking deduplicates domains."""
    manager = HostsManager(temp_hosts)

    # Block with duplicates
    manager.block_sites(["example.com", "example.com", "test.com"])

    content = temp_hosts.read_text()

    # Count occurrences (should appear once, plus once for www variant)
    example_count = content.count("0.0.0.0 example.com\n")
    assert example_count == 1


def test_block_sites_multiple_times(temp_hosts: Path) -> None:
    """Test that blocking multiple times updates correctly."""
    manager = HostsManager(temp_hosts)

    # First block
    manager.block_sites(["example.com"])
    assert manager.is_blocked("example.com")

    # Second block with different domain
    manager.block_sites(["test.com"])

    # Both should be blocked
    assert manager.is_blocked("example.com")
    assert manager.is_blocked("test.com")


def test_get_info(temp_hosts: Path) -> None:
    """Test getting hosts file information."""
    manager = HostsManager(temp_hosts)

    info = manager.get_info()

    assert info["exists"] is True
    assert info["readable"] is True
    assert info["blocked_count"] == 0

    # After blocking
    manager.block_sites(["example.com"])
    info = manager.get_info()

    assert info["blocked_count"] > 0
    assert "example.com" in info["blocked_domains"]


def test_nonexistent_hosts_file(tmp_path: Path) -> None:
    """Test handling of nonexistent hosts file."""
    fake_hosts = tmp_path / "nonexistent"
    manager = HostsManager(fake_hosts)

    with pytest.raises(FileNotFoundError):
        manager.read_hosts()

    info = manager.get_info()
    assert info["exists"] is False
    assert info["readable"] is False
