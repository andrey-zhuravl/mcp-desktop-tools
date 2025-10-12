"""open_recent tool implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import fnmatch
import logging
import os
import time

from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import normalize_workspace_path, path_in_workspace

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "open_recent"


@dataclass
class OpenRecentRequest:
    workspace_id: str
    rel_path: Optional[str] = None
    count: Optional[int] = None
    extensions: List[str] = field(default_factory=list)
    include_globs: List[str] = field(default_factory=list)
    exclude_globs: List[str] = field(default_factory=list)
    since: Optional[str] = None
    follow_symlinks: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "OpenRecentRequest":
        if "workspace_id" not in data:
            raise ValueError("workspace_id is required")

        def _list(name: str) -> List[str]:
            value = data.get(name)
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item) for item in value]
            raise ValueError(f"{name} must be a list of strings")

        count = data.get("count")
        if count is not None and (not isinstance(count, int) or count <= 0):
            raise ValueError("count must be a positive integer")

        since = data.get("since")
        if since is not None and not isinstance(since, str):
            raise ValueError("since must be an ISO8601 string")

        return cls(
            workspace_id=str(data["workspace_id"]),
            rel_path=str(data.get("rel_path")) if data.get("rel_path") is not None else None,
            count=count if isinstance(count, int) else None,
            extensions=_list("extensions"),
            include_globs=_list("include_globs"),
            exclude_globs=_list("exclude_globs"),
            since=since if isinstance(since, str) else None,
            follow_symlinks=bool(data.get("follow_symlinks", False)),
        )


@dataclass
class RecentFile:
    path: str
    abs_path: str
    mtime: str
    bytes: int


@dataclass
class OpenRecentData:
    files: List[RecentFile] = field(default_factory=list)
    total_scanned: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "files": [file.__dict__ for file in self.files],
            "total_scanned": self.total_scanned,
        }


@dataclass
class OpenRecentResponse:
    ok: bool
    data: OpenRecentData
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, int] = field(default_factory=dict)
    error: Optional[Dict[str, object]] = None

    def to_dict(self) -> Dict[str, object]:
        payload = {
            "ok": self.ok,
            "data": self.data.to_dict(),
            "warnings": self.warnings,
            "metrics": self.metrics,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


def _normalize_patterns(patterns: List[str]) -> List[str]:
    return [pattern for pattern in patterns if pattern]


def _matches_any(patterns: List[str], path: str) -> bool:
    if not patterns:
        return False
    candidates = [path, f"./{path}"]
    if not path.endswith("/"):
        candidates.extend([f"{path}/", f"./{path}/"])
    for pattern in patterns:
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern):
                return True
    return False


def _parse_since(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    sanitized = value.rstrip()
    if sanitized.endswith("Z"):
        sanitized = sanitized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(sanitized)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def execute(request: OpenRecentRequest, config: WorkspacesConfig) -> OpenRecentResponse:
    start = time.perf_counter()
    data = OpenRecentData()

    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return OpenRecentResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "workspace_not_found", "message": str(exc)},
        )

    try:
        ensure_tool_allowed(workspace, TOOL_NAME)
    except PermissionError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return OpenRecentResponse(
            ok=False,
            data=data,
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.rel_path) if request.rel_path else None)
    if not validation.ok or validation.path is None:
        elapsed = int((time.perf_counter() - start) * 1000)
        reason = validation.reason or "Invalid path"
        return OpenRecentResponse(
            ok=False,
            data=data,
            warnings=[reason],
            metrics={"elapsed_ms": elapsed},
            error={"type": "path_error", "message": reason},
        )

    base_path = validation.path

    include_patterns = _normalize_patterns(request.include_globs)
    exclude_patterns = _normalize_patterns(list(workspace.excludes) + request.exclude_globs)

    extensions = {ext.lower() for ext in request.extensions if ext}
    try:
        since_dt = _parse_since(request.since)
    except ValueError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return OpenRecentResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "invalid_request", "message": str(exc)},
        )

    limit = request.count or getattr(config.limits, "recent_files_count", 50)

    files: List[RecentFile] = []
    total_scanned = 0
    fs_walk_count = 0

    for root, dirs, filenames in os.walk(base_path, followlinks=request.follow_symlinks):
        fs_walk_count += 1
        root_path = Path(root)

        # Filter directories in-place using exclude patterns
        workspace_root = workspace.path.resolve()

        for idx in range(len(dirs) - 1, -1, -1):
            dir_name = dirs[idx]
            abs_dir = root_path / dir_name
            try:
                rel_dir = abs_dir.resolve().relative_to(workspace_root).as_posix()
            except ValueError:
                rel_dir = os.path.relpath(abs_dir, workspace_root)
            if _matches_any(exclude_patterns, rel_dir):
                dirs.pop(idx)

        for name in filenames:
            abs_file = root_path / name
            try:
                rel_path = abs_file.resolve().relative_to(workspace_root).as_posix()
            except ValueError:
                rel_path = os.path.relpath(abs_file, workspace_root)
            total_scanned += 1

            if _matches_any(exclude_patterns, rel_path):
                continue
            if include_patterns and not _matches_any(include_patterns, rel_path):
                continue
            if extensions and Path(name).suffix.lower() not in extensions:
                continue
            if not path_in_workspace(workspace.path, abs_file, follow_symlinks=request.follow_symlinks):
                continue

            try:
                stat_result = abs_file.stat()
            except OSError:
                continue

            mtime = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
            if since_dt and mtime < since_dt:
                continue

            files.append(
                RecentFile(
                    path=rel_path,
                    abs_path=str(abs_file),
                    mtime=mtime.isoformat(),
                    bytes=int(stat_result.st_size),
                )
            )

    files.sort(key=lambda item: item.mtime, reverse=True)
    if limit and len(files) > limit:
        files = files[:limit]

    data.files = files
    data.total_scanned = total_scanned

    elapsed = int((time.perf_counter() - start) * 1000)
    metrics = {"elapsed_ms": elapsed, "fs_walk_count": fs_walk_count}

    return OpenRecentResponse(
        ok=True,
        data=data,
        warnings=[],
        metrics=metrics,
    )


def execute_from_cli(args: Dict[str, object], config: WorkspacesConfig) -> OpenRecentResponse:
    request = OpenRecentRequest.from_dict(args)
    return execute(request, config)

