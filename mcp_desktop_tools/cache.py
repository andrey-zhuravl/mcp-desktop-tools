"""Caching utilities for MCP Desktop Tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple
import hashlib
import logging
import os
import pickle
import threading
import time
from collections import OrderedDict

try:  # pragma: no cover - optional dependency guarded at runtime
    from diskcache import Cache as DiskCache
except ImportError:  # pragma: no cover - handled gracefully in runtime
    DiskCache = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

CACHE_DIR_ENV = "MCPDT_CACHE_DIR"
CACHE_TTL_ENV = "MCPDT_CACHE_TTL_SEC"
CACHE_DISABLE_ENV = "MCPDT_DISABLE_CACHE"

DEFAULT_CACHE_DIR = Path("~/.mcpdt/cache").expanduser()
DEFAULT_DISK_TTL = 3600
SEARCH_CACHE_TTL = 120
DEFAULT_MAX_CACHE_BYTES = 200_000_000
DEFAULT_MAX_ENTRY_BYTES = 5_000_000
DEFAULT_SEARCH_CACHE_SIZE = 256


@dataclass(frozen=True)
class CacheSettings:
    """Describes runtime cache configuration."""

    enabled: bool
    cache_dir: Path
    disk_ttl: int
    search_ttl: int
    max_cache_bytes: int
    max_entry_bytes: int


_settings_lock = threading.Lock()
_settings: Optional[CacheSettings] = None
_disk_cache: Optional[object] = None
_search_cache: Optional["SimpleTTLCache"] = None


def _load_settings() -> CacheSettings:
    enabled = os.environ.get(CACHE_DISABLE_ENV) != "1"
    cache_dir_raw = os.environ.get(CACHE_DIR_ENV)
    cache_dir = Path(cache_dir_raw).expanduser() if cache_dir_raw else DEFAULT_CACHE_DIR
    disk_ttl_raw = os.environ.get(CACHE_TTL_ENV)
    try:
        disk_ttl = int(disk_ttl_raw) if disk_ttl_raw else DEFAULT_DISK_TTL
    except ValueError:
        LOGGER.warning("Invalid MCPDT_CACHE_TTL_SEC=%s, using default %s", disk_ttl_raw, DEFAULT_DISK_TTL)
        disk_ttl = DEFAULT_DISK_TTL
    return CacheSettings(
        enabled=enabled,
        cache_dir=cache_dir,
        disk_ttl=max(1, disk_ttl),
        search_ttl=SEARCH_CACHE_TTL,
        max_cache_bytes=DEFAULT_MAX_CACHE_BYTES,
        max_entry_bytes=DEFAULT_MAX_ENTRY_BYTES,
    )


def get_cache_settings() -> CacheSettings:
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = _load_settings()
    return _settings


def reset_cache_state() -> None:
    """Reset global cache state (used by tests)."""

    global _settings, _disk_cache, _search_cache
    with _settings_lock:
        _settings = None
        if _disk_cache is not None:
            try:
                _disk_cache.close()
            except Exception:  # pragma: no cover - best effort cleanup
                LOGGER.debug("Failed to close disk cache", exc_info=True)
        _disk_cache = None
        _search_cache = None


def _ensure_disk_cache(settings: CacheSettings) -> Optional[DiskCache]:
    if not settings.enabled:
        return None
    global _disk_cache
    if _disk_cache is None:
        cache_dir = settings.cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        if DiskCache is not None:
            _disk_cache = DiskCache(directory=str(cache_dir), size_limit=settings.max_cache_bytes)
        else:
            _disk_cache = FileCache(cache_dir, settings.max_cache_bytes)
    return _disk_cache


def get_disk_cache() -> Optional[DiskCache]:
    """Return shared disk cache instance if enabled."""

    settings = get_cache_settings()
    return _ensure_disk_cache(settings)


class SimpleTTLCache:
    def __init__(self, maxsize: int, ttl: int) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: "OrderedDict[str, Tuple[Any, float]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            value, timestamp = entry
            if (time.time() - timestamp) > self._ttl:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, time.time())
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)


class FileCache:
    def __init__(self, directory: Path, size_limit: int) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._size_limit = size_limit
        self._lock = threading.Lock()

    def _path_for(self, key: str) -> Path:
        return self._directory / key

    def get(self, key: str) -> Optional[Any]:
        path = self._path_for(key)
        with self._lock:
            if not path.exists():
                return None
            try:
                with path.open("rb") as stream:
                    payload = pickle.load(stream)
            except (OSError, pickle.PickleError):
                LOGGER.debug("Failed to load cache entry %s", path, exc_info=True)
                _safe_unlink(path)
                return None
            expire_at = payload.get("expire_at")
            if expire_at is not None and expire_at < time.time():
                _safe_unlink(path)
                return None
            return payload.get("value")

    def set(self, key: str, value: Any, expire: int) -> None:
        path = self._path_for(key)
        tmp_path = path.with_suffix(".tmp")
        payload = {"value": value, "expire_at": (time.time() + expire) if expire else None}
        data = serialize_entry(payload)
        with self._lock:
            try:
                with tmp_path.open("wb") as stream:
                    stream.write(data)
                tmp_path.replace(path)
            except OSError:
                LOGGER.debug("Failed to write cache entry %s", path, exc_info=True)
                _safe_unlink(tmp_path)
                return
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        total = 0
        files: List[Tuple[float, Path, int]] = []
        for candidate in self._directory.glob("*"):
            if candidate.suffix == ".tmp":
                continue
            try:
                stat = candidate.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, candidate, stat.st_size))
            total += stat.st_size
        if total <= self._size_limit:
            return
        files.sort(key=lambda item: item[0])
        for _, candidate, size in files:
            if total <= self._size_limit:
                break
            _safe_unlink(candidate)
            total -= size


def get_search_cache() -> Optional[SimpleTTLCache]:
    """Return shared in-memory cache for search_text if enabled."""

    settings = get_cache_settings()
    if not settings.enabled:
        return None
    global _search_cache
    if _search_cache is None:
        _search_cache = SimpleTTLCache(maxsize=DEFAULT_SEARCH_CACHE_SIZE, ttl=settings.search_ttl)
    return _search_cache


def build_cache_key(parts: Iterable[object]) -> str:
    """Build a deterministic cache key from an iterable of objects."""

    hasher = hashlib.blake2b(digest_size=32)
    for part in parts:
        if isinstance(part, (bytes, bytearray)):
            data = bytes(part)
        else:
            data = repr(part).encode("utf-8", errors="ignore")
        hasher.update(data)
        hasher.update(b"\x00")
    return hasher.hexdigest()


def serialize_entry(value: Any) -> bytes:
    """Serialize *value* using pickle for cache storage."""

    return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)


def ensure_entry_within_limit(value: Any, *, max_bytes: int) -> bool:
    """Return True if serialized *value* fits inside configured size limit."""

    size = len(serialize_entry(value))
    return size <= max_bytes


def now_ms() -> int:
    return int(time.time() * 1000)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        LOGGER.debug("Failed to remove %s", path, exc_info=True)

