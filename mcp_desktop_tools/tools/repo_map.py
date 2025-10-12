"""Implementation of the repo_map MCP tool with caching and concurrency."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import concurrent.futures
import heapq
import hashlib
import logging
import os
import time

from pathspec import PathSpec

from ..cache import (
    build_cache_key,
    ensure_entry_within_limit,
    get_cache_settings,
    get_disk_cache,
)
from ..config import WorkspacesConfig, ensure_tool_allowed
from ..concurrency import resolve_max_workers, stat_paths
from ..metrics import ProfileCollector, add_profile
from ..security import clamp_depth, merge_excludes, normalize_workspace_path, path_in_workspace

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "repo_map"
LARGEST_FILES_LIMIT = 50
MAX_WORKERS_ENV = "MCPDT_MAX_WORKERS"
FS_BATCH_SIZE = 256


LANGUAGE_BY_EXTENSION: Dict[str, str] = {
    ".py": "Python",
    ".md": "Markdown",
    ".json": "JSON",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".css": "CSS",
    ".html": "HTML",
    ".xml": "XML",
    ".toml": "TOML",
    ".ini": "INI",
    ".cfg": "INI",
    ".sh": "Shell",
    ".bat": "Batch",
    ".ps1": "PowerShell",
}


@dataclass
class RepoMapRequest:
    workspace_id: str
    rel_path: str
    max_depth: Optional[int] = None
    top_dirs: Optional[int] = None
    by_language: bool = True
    follow_symlinks: Optional[bool] = None
    include_globs: List[str] = field(default_factory=list)
    exclude_globs: List[str] = field(default_factory=list)
    disable_cache: bool = False
    profile: bool = False
    max_workers: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "RepoMapRequest":
        if "workspace_id" not in data:
            raise ValueError("workspace_id is required")
        if "rel_path" not in data:
            raise ValueError("rel_path is required")

        def _list(name: str) -> List[str]:
            value = data.get(name)
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item) for item in value]
            raise ValueError(f"{name} must be a list of strings")

        return cls(
            workspace_id=str(data["workspace_id"]),
            rel_path=str(data["rel_path"]),
            max_depth=int(data["max_depth"]) if data.get("max_depth") is not None else None,
            top_dirs=int(data["top_dirs"]) if data.get("top_dirs") is not None else None,
            by_language=bool(data.get("by_language", True)),
            follow_symlinks=bool(data["follow_symlinks"]) if data.get("follow_symlinks") is not None else None,
            include_globs=_list("include_globs"),
            exclude_globs=_list("exclude_globs"),
            disable_cache=bool(data.get("disable_cache", False)),
            profile=bool(data.get("profile", False)),
            max_workers=int(data["max_workers"]) if data.get("max_workers") is not None else None,
        )


@dataclass
class RepoMapSummary:
    files: int
    bytes: int

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RepoMapSummary":
        return cls(files=int(payload.get("files", 0)), bytes=int(payload.get("bytes", 0)))


@dataclass
class RepoMapDirStat:
    dir: str
    files: int
    bytes: int

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RepoMapDirStat":
        return cls(
            dir=str(payload.get("dir", "")),
            files=int(payload.get("files", 0)),
            bytes=int(payload.get("bytes", 0)),
        )


@dataclass
class RepoMapData:
    summary: RepoMapSummary
    top: List[RepoMapDirStat]
    extensions: Dict[str, int]
    languages: Dict[str, int]
    largest_files: List[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return {
            "summary": self.summary.__dict__,
            "top": [item.__dict__ for item in self.top],
            "extensions": self.extensions,
            "languages": self.languages,
            "largest_files": self.largest_files,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RepoMapData":
        summary_payload = payload.get("summary")
        top_payload = payload.get("top")
        extensions = payload.get("extensions")
        languages = payload.get("languages")
        largest = payload.get("largest_files")
        summary = RepoMapSummary.from_dict(summary_payload if isinstance(summary_payload, dict) else {})
        top: List[RepoMapDirStat] = []
        if isinstance(top_payload, list):
            for item in top_payload:
                if isinstance(item, dict):
                    top.append(RepoMapDirStat.from_dict(item))
        return cls(
            summary=summary,
            top=top,
            extensions=dict(extensions) if isinstance(extensions, dict) else {},
            languages=dict(languages) if isinstance(languages, dict) else {},
            largest_files=list(largest) if isinstance(largest, list) else [],
        )


@dataclass
class RepoMapResponse:
    ok: bool
    data: RepoMapData
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)
    error: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, object]:
        payload = {
            "ok": self.ok,
            "data": self.data.to_dict(),
            "warnings": self.warnings,
            "metrics": self.metrics,
        }
        if self.error:
            payload["error"] = self.error
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "RepoMapResponse":
        data_payload = payload.get("data")
        data = RepoMapData.from_dict(data_payload if isinstance(data_payload, dict) else {})
        warnings = payload.get("warnings")
        metrics = payload.get("metrics")
        error = payload.get("error")
        return cls(
            ok=bool(payload.get("ok", False)),
            data=data,
            warnings=list(warnings) if isinstance(warnings, list) else [],
            metrics=dict(metrics) if isinstance(metrics, dict) else {},
            error=dict(error) if isinstance(error, dict) else None,
        )


def _compile_spec(patterns: Iterable[str]) -> Optional[PathSpec]:
    patterns = [p for p in patterns if p]
    if not patterns:
        return None
    return PathSpec.from_lines("gitwildmatch", patterns)


def _language_for_extension(ext: str) -> Optional[str]:
    return LANGUAGE_BY_EXTENSION.get(ext.lower())


def _should_skip(relative: str, *, spec: Optional[PathSpec]) -> bool:
    if not spec:
        return False
    return spec.match_file(relative)


def _record_largest(heap: List[Tuple[int, str]], limit: int, size: int, rel_path: str) -> None:
    entry = (size, rel_path)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
        return
    if size > heap[0][0]:
        heapq.heapreplace(heap, entry)


def _compute_tree_signature(
    base_path: Path,
    *,
    follow_symlinks: bool,
    effective_depth: Optional[int],
    exclude_spec: Optional[PathSpec],
) -> str:
    hasher = hashlib.blake2b(digest_size=32)
    for root, dirs, _ in os.walk(base_path, followlinks=follow_symlinks):
        relative_root = Path(root).relative_to(base_path)
        depth = 0 if str(relative_root) == "." else len(relative_root.parts)
        if effective_depth is not None and depth >= effective_depth:
            dirs[:] = []
            continue
        for idx in range(len(dirs) - 1, -1, -1):
            rel_dir = Path(root, dirs[idx]).relative_to(base_path).as_posix()
            if _should_skip(rel_dir, spec=exclude_spec):
                dirs.pop(idx)
        rel_text = relative_root.as_posix() or "."
        try:
            stat = Path(root).stat(follow_symlinks=follow_symlinks)
        except OSError:
            continue
        hasher.update(rel_text.encode("utf-8"))
        hasher.update(str(int(stat.st_mtime_ns)).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("utf-8"))
    return hasher.hexdigest()


def execute(request: RepoMapRequest, config: WorkspacesConfig) -> RepoMapResponse:
    start = time.perf_counter()
    profile = ProfileCollector(request.profile)
    cache_settings = get_cache_settings()
    disk_cache = get_disk_cache() if not request.disable_cache else None
    cache_key: Optional[str] = None

    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        empty = RepoMapData(
            summary=RepoMapSummary(files=0, bytes=0),
            top=[],
            extensions={},
            languages={},
            largest_files=[],
        )
        return RepoMapResponse(
            ok=False,
            data=empty,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "workspace_not_found", "message": str(exc)},
        )

    try:
        ensure_tool_allowed(workspace, TOOL_NAME)
    except PermissionError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        empty = RepoMapData(
            summary=RepoMapSummary(files=0, bytes=0),
            top=[],
            extensions={},
            languages={},
            largest_files=[],
        )
        return RepoMapResponse(
            ok=False,
            data=empty,
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.rel_path))
    if not validation.ok or validation.path is None:
        elapsed = int((time.perf_counter() - start) * 1000)
        empty = RepoMapData(
            summary=RepoMapSummary(files=0, bytes=0),
            top=[],
            extensions={},
            languages={},
            largest_files=[],
        )
        reason = validation.reason or "Invalid path"
        return RepoMapResponse(
            ok=False,
            data=empty,
            warnings=[reason],
            metrics={"elapsed_ms": elapsed},
            error={"type": "path_error", "message": reason},
        )

    base_path = validation.path

    requested_depth = request.max_depth if request.max_depth is not None else config.limits.repo_map_max_depth
    effective_depth = clamp_depth(requested_depth, workspace.max_depth)

    top_limit = config.limits.repo_map_top_dirs if request.top_dirs is None else max(0, request.top_dirs)
    warnings: List[str] = []
    if top_limit > config.limits.repo_map_top_dirs:
        warnings.append(
            f"Requested top_dirs={top_limit} exceeds configured limit {config.limits.repo_map_top_dirs}; using {config.limits.repo_map_top_dirs}"
        )
        top_limit = config.limits.repo_map_top_dirs

    follow_symlinks = (
        request.follow_symlinks
        if request.follow_symlinks is not None
        else config.limits.repo_map_follow_symlinks
    )

    include_spec = _compile_spec(request.include_globs)
    exclude_patterns = merge_excludes(workspace, request.exclude_globs)
    exclude_spec = _compile_spec(exclude_patterns)

    env_workers_value = os.environ.get(MAX_WORKERS_ENV)
    env_workers: Optional[int] = None
    if env_workers_value:
        try:
            env_workers = int(env_workers_value)
        except ValueError:
            LOGGER.warning("Invalid MCPDT_MAX_WORKERS=%s; ignoring", env_workers_value)
            env_workers = None

    max_workers = resolve_max_workers(request.max_workers, env_workers)

    tree_signature: Optional[str] = None
    if disk_cache is not None:
        with profile.stage("signature"):
            tree_signature = _compute_tree_signature(
                base_path,
                follow_symlinks=follow_symlinks,
                effective_depth=effective_depth,
                exclude_spec=exclude_spec,
            )
        cache_parts = (
            "repo_map",
            request.workspace_id,
            str(base_path),
            effective_depth,
            top_limit,
            follow_symlinks,
            tuple(sorted(request.include_globs)),
            tuple(sorted(exclude_patterns)),
            request.by_language,
            tree_signature,
            config.limits.max_file_size_bytes,
        )
        cache_key = build_cache_key(cache_parts)
        with profile.stage("cache_lookup"):
            cached_payload = disk_cache.get(cache_key)
        if cached_payload is not None:
            cached_response = RepoMapResponse.from_dict(cached_payload)
            metrics = dict(cached_response.metrics)
            metrics.update(
                {
                    "elapsed_ms": int((time.perf_counter() - start) * 1000),
                    "cache_hit": True,
                    "cache_key": cache_key,
                    "max_workers": max_workers,
                }
            )
            metrics = add_profile(metrics, profile)
            cached_response.metrics = metrics
            return cached_response

    summary_files = 0
    summary_bytes = 0
    dir_counters: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    ext_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    largest_heap: List[Tuple[int, str]] = []
    fs_walk_count = 0
    bytes_scanned = 0

    def _process_stat(result) -> None:
        nonlocal summary_files, summary_bytes, bytes_scanned
        if result.error:
            rel_display = result.rel_path.as_posix()
            warnings.append(f"Failed to read file metadata: {rel_display}")
            return
        stat = result.stat
        if stat is None:
            return
        size = stat.st_size
        if size > config.limits.max_file_size_bytes:
            warnings.append(
                f"Skipped {result.rel_path.as_posix()} due to size > {config.limits.max_file_size_bytes}"
            )
            return
        summary_files += 1
        summary_bytes += size
        bytes_scanned += size
        parent = result.rel_path.parent.as_posix() if result.rel_path.parent.as_posix() != "." else "."
        counter = dir_counters[parent]
        counter[0] += 1
        counter[1] += size
        ext = result.rel_path.suffix or ""
        ext_counter[ext] += 1
        if request.by_language:
            language = _language_for_extension(ext)
            if language:
                lang_counter[language] += 1
        _record_largest(largest_heap, LARGEST_FILES_LIMIT, size, result.rel_path.as_posix())

    with profile.stage("walk"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            batch: List[Tuple[Path, Path]] = []
            for root, dirs, files in os.walk(base_path, followlinks=follow_symlinks):
                fs_walk_count += 1
                relative_root = Path(root).relative_to(base_path)
                depth = 0 if str(relative_root) == "." else len(relative_root.parts)
                if effective_depth is not None and depth >= effective_depth:
                    dirs[:] = []
                    continue
                for idx in range(len(dirs) - 1, -1, -1):
                    rel_dir = Path(root, dirs[idx]).relative_to(base_path).as_posix()
                    if _should_skip(rel_dir, spec=exclude_spec):
                        dirs.pop(idx)
                for file_name in files:
                    file_path = Path(root, file_name)
                    rel_path = file_path.relative_to(base_path)
                    rel_posix = rel_path.as_posix()
                    if _should_skip(rel_posix, spec=exclude_spec):
                        continue
                    if include_spec and not include_spec.match_file(rel_posix):
                        continue
                    if file_path.is_symlink() and not follow_symlinks:
                        continue
                    if not path_in_workspace(workspace.path, file_path, follow_symlinks=follow_symlinks):
                        warnings.append(f"Skipped {rel_posix} due to workspace escape")
                        continue
                    batch.append((file_path, rel_path))
                    if len(batch) >= FS_BATCH_SIZE:
                        for stat_result in stat_paths(executor, batch, follow_symlinks=follow_symlinks):
                            _process_stat(stat_result)
                        batch = []
            if batch:
                for stat_result in stat_paths(executor, batch, follow_symlinks=follow_symlinks):
                    _process_stat(stat_result)

    top_entries = [
        RepoMapDirStat(dir=key, files=value[0], bytes=value[1])
        for key, value in dir_counters.items()
    ]
    top_entries.sort(key=lambda item: item.bytes, reverse=True)
    if len(top_entries) > top_limit:
        warnings.append("Truncated top directories list")
        top_entries = top_entries[:top_limit]

    largest_files = [
        {"path": path, "bytes": size}
        for size, path in sorted(largest_heap, key=lambda item: item[0], reverse=True)
    ]

    data = RepoMapData(
        summary=RepoMapSummary(files=summary_files, bytes=summary_bytes),
        top=top_entries,
        extensions=dict(ext_counter),
        languages=dict(lang_counter) if request.by_language else {},
        largest_files=largest_files,
    )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    metrics: Dict[str, object] = {
        "elapsed_ms": elapsed_ms,
        "fs_walk_count": fs_walk_count,
        "bytes_scanned": bytes_scanned,
        "cache_hit": False,
        "max_workers": max_workers,
    }
    if cache_key:
        metrics["cache_key"] = cache_key
    metrics = add_profile(metrics, profile)

    response = RepoMapResponse(ok=True, data=data, warnings=warnings, metrics=metrics)

    if disk_cache is not None and cache_key:
        payload = response.to_dict()
        if ensure_entry_within_limit(payload, max_bytes=cache_settings.max_entry_bytes):
            disk_cache.set(cache_key, payload, expire=cache_settings.disk_ttl)

    return response

