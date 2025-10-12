"""Implementation of the repo_map MCP tool."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import heapq
import logging
import os
import time

from pathspec import PathSpec

from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import clamp_depth, merge_excludes, normalize_workspace_path, path_in_workspace

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "repo_map"
LARGEST_FILES_LIMIT = 50

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
        )


@dataclass
class RepoMapSummary:
    files: int
    bytes: int


@dataclass
class RepoMapDirStat:
    dir: str
    files: int
    bytes: int


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


@dataclass
class RepoMapResponse:
    ok: bool
    data: RepoMapData
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, int] = field(default_factory=dict)
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


def _compile_spec(patterns: Iterable[str]) -> Optional[PathSpec]:
    patterns = [p for p in patterns if p]
    if not patterns:
        return None
    return PathSpec.from_lines("gitwildmatch", patterns)


def _language_for_extension(ext: str) -> Optional[str]:
    return LANGUAGE_BY_EXTENSION.get(ext.lower())


def _should_skip(path: Path, *, spec: Optional[PathSpec]) -> bool:
    if not spec:
        return False
    relative = path.as_posix()
    return spec.match_file(relative)


def _record_largest(
    heap: List[Tuple[int, str]],
    limit: int,
    size: int,
    rel_path: str,
) -> None:
    entry = (size, rel_path)
    if len(heap) < limit:
        heapq.heappush(heap, entry)
        return
    if size > heap[0][0]:
        heapq.heapreplace(heap, entry)


def execute(request: RepoMapRequest, config: WorkspacesConfig) -> RepoMapResponse:
    start = time.perf_counter()
    warnings: List[str] = []

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

    top_limit = config.limits.repo_map_top_dirs if request.top_dirs is None else request.top_dirs
    if top_limit < 0:
        top_limit = 0
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

    summary_files = 0
    summary_bytes = 0
    dir_counters: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    ext_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    largest_heap: List[Tuple[int, str]] = []
    fs_walk_count = 0
    bytes_scanned = 0

    for root, dirs, files in os.walk(base_path, followlinks=follow_symlinks):
        fs_walk_count += 1
        relative_root = Path(root).relative_to(base_path)
        depth = 0 if str(relative_root) == "." else len(relative_root.parts)
        if effective_depth is not None and depth >= effective_depth:
            dirs[:] = []
            continue

        # Apply directory excludes eagerly
        for idx in range(len(dirs) - 1, -1, -1):
            dir_name = dirs[idx]
            rel_dir = Path(root, dir_name).relative_to(base_path).as_posix()
            if _should_skip(Path(rel_dir), spec=exclude_spec):
                dirs.pop(idx)

        for file_name in files:
            file_path = Path(root, file_name)
            rel_path = file_path.relative_to(base_path)
            rel_posix = rel_path.as_posix()

            if _should_skip(Path(rel_posix), spec=exclude_spec):
                continue

            if include_spec and not include_spec.match_file(rel_posix):
                continue

            try:
                if file_path.is_symlink() and not follow_symlinks:
                    continue
                if not path_in_workspace(workspace.path, file_path, follow_symlinks=follow_symlinks):
                    warnings.append(f"Skipped {rel_posix} due to workspace escape")
                    continue
                stat = file_path.stat(follow_symlinks=follow_symlinks)
            except OSError:
                warnings.append(f"Failed to read file metadata: {rel_posix}")
                continue

            size = stat.st_size
            if size > config.limits.max_file_size_bytes:
                warnings.append(f"Skipped {rel_posix} due to size > {config.limits.max_file_size_bytes}")
                continue

            summary_files += 1
            summary_bytes += size
            bytes_scanned += size

            parent = rel_path.parent.as_posix() if str(rel_path.parent) != "." else "."
            counter = dir_counters[parent]
            counter[0] += 1
            counter[1] += size

            ext = rel_path.suffix or ""
            ext_counter[ext] += 1
            if request.by_language:
                language = _language_for_extension(ext)
                if language:
                    lang_counter[language] += 1

            _record_largest(largest_heap, LARGEST_FILES_LIMIT, size, rel_posix)

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

    metrics = {
        "elapsed_ms": int((time.perf_counter() - start) * 1000),
        "fs_walk_count": fs_walk_count,
        "bytes_scanned": bytes_scanned,
    }

    return RepoMapResponse(ok=True, data=data, warnings=warnings, metrics=metrics)
