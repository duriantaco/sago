import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SmartCache:
    def __init__(self, cache_dir: Path | None = None, ttl_hours: int = 24) -> None:
        self.cache_dir = cache_dir or Path.home() / ".sago" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_task_hash(self, task_data: dict[str, Any]) -> str:
        hash_data = {
            "id": task_data.get("id"),
            "name": task_data.get("name"),
            "action": task_data.get("action"),
            "files": sorted(task_data.get("files", [])),
            "verify": task_data.get("verify"),
            "done": task_data.get("done"),
        }

        if "file_contents" in task_data:
            hash_data["file_contents"] = task_data["file_contents"]

        json_str = json.dumps(hash_data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def get_cached_result(self, task_hash: str) -> dict[str, Any] | None:
        cache_file = self.cache_dir / f"{task_hash}.json"

        if not cache_file.exists():
            self.logger.debug(f"Cache miss: {task_hash[:8]}")
            return None

        try:
            with open(cache_file, encoding="utf-8") as f:
                cache_data = json.load(f)

            cached_time = datetime.fromisoformat(cache_data["timestamp"])
            if datetime.now() - cached_time > self.ttl:
                self.logger.info(f"Cache expired: {task_hash[:8]}")
                cache_file.unlink()
                return None

            self.logger.info(f"Cache hit: {task_hash[:8]}")
            result: dict[str, Any] = cache_data["result"]
            return result

        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.warning(f"Error reading cache: {e}")
            return None

    def set_cached_result(self, task_hash: str, result: dict[str, Any]) -> None:
        cache_file = self.cache_dir / f"{task_hash}.json"

        try:
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "task_hash": task_hash,
                "result": result,
            }

            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)

            self.logger.info(f"Cached result: {task_hash[:8]}")

        except (OSError, TypeError, ValueError) as e:
            self.logger.warning(f"Error writing cache: {e}")

    def invalidate_task(self, task_hash: str) -> None:
        cache_file = self.cache_dir / f"{task_hash}.json"
        if cache_file.exists():
            cache_file.unlink()
            self.logger.info(f"Invalidated cache: {task_hash[:8]}")

    def clear_all(self) -> int:
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
            count += 1

        self.logger.info(f"Cleared {count} cache files")
        return count

    def get_cache_stats(self) -> dict[str, Any]:
        cache_files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in cache_files)

        expired = 0
        for cache_file in cache_files:
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cache_data = json.load(f)
                cached_time = datetime.fromisoformat(cache_data["timestamp"])
                if datetime.now() - cached_time > self.ttl:
                    expired += 1
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                pass

        return {
            "total_entries": len(cache_files),
            "expired_entries": expired,
            "total_size_bytes": total_size,
            "total_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(self.cache_dir),
        }

    def cleanup_expired(self) -> int:
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cache_data = json.load(f)
                cached_time = datetime.fromisoformat(cache_data["timestamp"])
                if datetime.now() - cached_time > self.ttl:
                    cache_file.unlink()
                    count += 1
            except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                self.logger.warning(f"Error cleaning cache file {cache_file}: {e}")

        self.logger.info(f"Cleaned up {count} expired cache entries")
        return count


class CacheManager:
    def __init__(self, cache: SmartCache | None = None) -> None:
        self.cache = cache or SmartCache()
        self.logger = logging.getLogger(self.__class__.__name__)

    def should_use_cache(self, task_data: dict[str, Any], project_path: Path) -> bool:
        files = task_data.get("files", [])
        for file_path_str in files:
            file_path = project_path / file_path_str
            if file_path.exists():
                self.logger.debug(f"File {file_path_str} exists, skipping cache")
                return False

        return True

    def get_or_execute(
        self,
        task_data: dict[str, Any],
        execute_fn: Callable[[], dict[str, Any]],
        project_path: Path,
    ) -> dict[str, Any]:
        if not self.should_use_cache(task_data, project_path):
            self.logger.info("Cache disabled for this task (files exist)")
            return execute_fn()

        task_hash = self.cache.get_task_hash(task_data)

        cached = self.cache.get_cached_result(task_hash)
        if cached:
            self.logger.info(f"Using cached result for task {task_data.get('id')}")
            return cached

        self.logger.info(f"Executing task {task_data.get('id')}")
        result = execute_fn()

        if result.get("success"):
            self.cache.set_cached_result(task_hash, result)

        return result

    def invalidate_by_file(self, file_path: str) -> int:
        count = 0
        cache_dir = self.cache.cache_dir

        for cache_file in cache_dir.glob("*.json"):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    cache_data = json.load(f)

                result = cache_data.get("result", {})
                files = result.get("files_modified", [])

                if file_path in files:
                    cache_file.unlink()
                    count += 1

            except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
                self.logger.warning(f"Error checking cache file: {e}")

        self.logger.info(f"Invalidated {count} cache entries for {file_path}")
        return count
