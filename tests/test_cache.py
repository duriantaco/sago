"""Tests for smart caching system."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sago.utils.cache import SmartCache


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    """Create a temporary cache directory."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture
def cache(cache_dir: Path) -> SmartCache:
    """Create a SmartCache instance with short TTL for testing."""
    return SmartCache(cache_dir=cache_dir, ttl_hours=1)


# --- Hash generation ---


def test_hash_deterministic(cache: SmartCache) -> None:
    """Same input produces same hash."""
    task_data = {"id": "1.1", "name": "test", "action": "do something", "files": ["a.py"]}
    h1 = cache.get_task_hash(task_data)
    h2 = cache.get_task_hash(task_data)
    assert h1 == h2


def test_hash_changes_with_content(cache: SmartCache) -> None:
    """Different input produces different hash."""
    base = {"id": "1.1", "name": "test", "action": "do something", "files": ["a.py"]}
    modified = {**base, "action": "do something else"}
    assert cache.get_task_hash(base) != cache.get_task_hash(modified)


def test_hash_includes_file_contents(cache: SmartCache) -> None:
    """File contents change the hash."""
    base = {"id": "1.1", "name": "test", "action": "act", "files": ["a.py"]}
    with_content = {**base, "file_contents": {"a.py": "print('hello')"}}
    assert cache.get_task_hash(base) != cache.get_task_hash(with_content)


def test_hash_file_order_irrelevant(cache: SmartCache) -> None:
    """File list order doesn't affect hash (files are sorted internally)."""
    data1 = {"id": "1", "name": "t", "action": "a", "files": ["b.py", "a.py"]}
    data2 = {"id": "1", "name": "t", "action": "a", "files": ["a.py", "b.py"]}
    assert cache.get_task_hash(data1) == cache.get_task_hash(data2)


def test_hash_is_sha256(cache: SmartCache) -> None:
    """Hash output is a 64-char hex string (SHA256)."""
    h = cache.get_task_hash({"id": "1", "name": "t", "action": "a", "files": []})
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_cache_miss_returns_none(cache: SmartCache) -> None:
    """Missing cache entry returns None."""
    assert cache.get_cached_result("nonexistent_hash") is None


def test_cache_set_then_get(cache: SmartCache) -> None:
    """Set a result, then retrieve it."""
    result = {"success": True, "files": {"a.py": "print(1)"}}
    cache.set_cached_result("abc123", result)
    cached = cache.get_cached_result("abc123")
    assert cached is not None
    assert cached["success"] is True
    assert cached["files"]["a.py"] == "print(1)"


def test_cache_creates_json_file(cache: SmartCache, cache_dir: Path) -> None:
    """Cached result is stored as a JSON file."""
    cache.set_cached_result("hash123", {"success": True})
    cache_file = cache_dir / "hash123.json"
    assert cache_file.exists()
    data = json.loads(cache_file.read_text())
    assert "timestamp" in data
    assert data["task_hash"] == "hash123"
    assert data["result"]["success"] is True


def test_cache_expired_returns_none(cache_dir: Path) -> None:
    """Expired cache entries return None and are deleted."""
    cache = SmartCache(cache_dir=cache_dir, ttl_hours=0)

    cache_file = cache_dir / "expired.json"
    expired_time = (datetime.now() - timedelta(hours=2)).isoformat()
    cache_file.write_text(
        json.dumps(
            {
                "timestamp": expired_time,
                "task_hash": "expired",
                "result": {"success": True},
            }
        )
    )

    assert cache.get_cached_result("expired") is None
    assert not cache_file.exists()


def test_invalidate_removes_entry(cache: SmartCache, cache_dir: Path) -> None:
    """Invalidation deletes the cache file."""
    cache.set_cached_result("to_delete", {"success": True})
    assert (cache_dir / "to_delete.json").exists()

    cache.invalidate_task("to_delete")
    assert not (cache_dir / "to_delete.json").exists()


def test_invalidate_nonexistent_is_noop(cache: SmartCache) -> None:
    """Invalidating a non-existent entry doesn't raise."""
    cache.invalidate_task("does_not_exist")


def test_clear_all(cache: SmartCache) -> None:
    """clear_all removes all entries and returns count."""
    cache.set_cached_result("h1", {"success": True})
    cache.set_cached_result("h2", {"success": True})
    cache.set_cached_result("h3", {"success": True})

    count = cache.clear_all()
    assert count == 3
    assert cache.get_cached_result("h1") is None


def test_cache_stats(cache: SmartCache) -> None:
    """get_cache_stats returns correct counts."""
    cache.set_cached_result("s1", {"success": True})
    cache.set_cached_result("s2", {"success": True})

    stats = cache.get_cache_stats()
    assert stats["total_entries"] == 2
    assert stats["total_size_bytes"] > 0
    assert stats["expired_entries"] == 0


def test_cleanup_expired(cache_dir: Path) -> None:
    """cleanup_expired removes only expired entries."""
    cache = SmartCache(cache_dir=cache_dir, ttl_hours=1)

    cache.set_cached_result("valid", {"success": True})
    expired_file = cache_dir / "old.json"
    expired_time = (datetime.now() - timedelta(hours=48)).isoformat()
    expired_file.write_text(
        json.dumps(
            {
                "timestamp": expired_time,
                "task_hash": "old",
                "result": {"success": True},
            }
        )
    )

    count = cache.cleanup_expired()
    assert count == 1
    assert not expired_file.exists()
    assert cache.get_cached_result("valid") is not None


def test_corrupt_cache_file_returns_none(cache: SmartCache, cache_dir: Path) -> None:
    corrupt_file = cache_dir / "corrupt.json"
    corrupt_file.write_text("not valid json {{{")

    assert cache.get_cached_result("corrupt") is None
