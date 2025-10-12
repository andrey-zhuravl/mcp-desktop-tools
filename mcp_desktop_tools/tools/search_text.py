"""Implementation of the search_text MCP tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import logging
import time

from ..adapters.rg import RipgrepRequest, RipgrepNotFoundError, run_ripgrep
from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import (
    clamp_depth,
    clamp_limits,
    merge_excludes,
    normalize_workspace_path,
)

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "search_text"


@dataclass
class SearchTextRequest:
    workspace_id: str
    query: str
    rel_path: Optional[str] = None
    regex: bool = True
    case_sensitive: bool = False
    include_globs: List[str] = field(default_factory=list)
    exclude_globs: List[str] = field(default_factory=list)
    max_matches: Optional[int] = None
    before: int = 0
    after: int = 0
    max_depth: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "SearchTextRequest":
        if "workspace_id" not in data or "query" not in data:
            raise ValueError("workspace_id and query are required")
        def _list(name: str) -> List[str]:
            value = data.get(name)
            if value is None:
                return []
            if isinstance(value, list):
                return [str(item) for item in value]
            raise ValueError(f"{name} must be a list of strings")

        return cls(
            workspace_id=str(data["workspace_id"]),
            query=str(data["query"]),
            rel_path=str(data.get("rel_path")) if data.get("rel_path") is not None else None,
            regex=bool(data.get("regex", True)),
            case_sensitive=bool(data.get("case_sensitive", False)),
            include_globs=_list("include_globs"),
            exclude_globs=_list("exclude_globs"),
            max_matches=int(data["max_matches"]) if data.get("max_matches") is not None else None,
            before=int(data.get("before", 0)),
            after=int(data.get("after", 0)),
            max_depth=int(data["max_depth"]) if data.get("max_depth") is not None else None,
        )


@dataclass
class SearchHit:
    file: str
    line: int
    text: str
    abs_path: Optional[str] = None


@dataclass
class SearchTextData:
    hits: List[SearchHit] = field(default_factory=list)
    total: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "hits": [hit.__dict__ for hit in self.hits],
            "total": self.total,
        }


@dataclass
class SearchTextResponse:
    ok: bool
    data: SearchTextData
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


def _estimate_hit_size(hit: SearchHit) -> int:
    return sum(len(str(value).encode("utf-8")) for value in (hit.file, hit.text, hit.abs_path or "")) + 32


def execute(request: SearchTextRequest, config: WorkspacesConfig) -> SearchTextResponse:
    start = time.perf_counter()
    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        LOGGER.error("Workspace not found: %s", request.workspace_id)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=[],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "workspace_not_found", "message": str(exc)},
        )

    try:
        ensure_tool_allowed(workspace, TOOL_NAME)
    except PermissionError as exc:
        LOGGER.warning("Tool not allowed for workspace %s", workspace.id)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.rel_path) if request.rel_path else None)
    if not validation.ok or validation.path is None:
        LOGGER.warning("Path validation failed for workspace %s: %s", workspace.id, validation.reason)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=[validation.reason or "Invalid path"],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "path_error", "message": validation.reason or "Invalid path"},
        )

    effective_depth = clamp_depth(request.max_depth, workspace.max_depth)
    limits = clamp_limits(
        config.limits,
        max_matches=request.max_matches,
    )

    exclude_globs = merge_excludes(workspace, request.exclude_globs)

    rg_request = RipgrepRequest(
        pattern=request.query,
        root=validation.path,
        rg_path=config.env.rg_path or "rg",
        regex=request.regex,
        case_sensitive=request.case_sensitive,
        include_globs=request.include_globs,
        exclude_globs=exclude_globs,
        max_matches=limits.max_matches,
        before=request.before,
        after=request.after,
        max_depth=effective_depth,
        max_file_size_bytes=limits.max_file_size_bytes,
    )

    try:
        result = run_ripgrep(rg_request)
    except RipgrepNotFoundError as exc:
        LOGGER.error("Ripgrep not available: %s", exc)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=["ripgrep binary not found"],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "missing_dependency", "message": str(exc)},
        )
    except RuntimeError as exc:
        LOGGER.error("Ripgrep failed: %s", exc)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=["ripgrep execution failed"],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "execution_error", "message": str(exc)},
        )

    hits: List[SearchHit] = []
    bytes_used = 0
    warnings = list(result.warnings)

    for hit in result.hits:
        if hit.file.is_absolute():
            try:
                rel_path = hit.file.relative_to(workspace.path)
            except ValueError:
                rel_path = hit.file.name
        else:
            rel_path = hit.file
        search_hit = SearchHit(
            file=str(rel_path),
            line=hit.line,
            text=hit.text,
            abs_path=str(hit.file.resolve(strict=False)) if hit.file.is_absolute() else str((workspace.path / hit.file).resolve(strict=False)),
        )
        hit_size = _estimate_hit_size(search_hit)
        if bytes_used + hit_size > limits.max_output_bytes:
            warnings.append("Truncated results due to output size limit")
            break
        hits.append(search_hit)
        bytes_used += hit_size
        if limits.max_matches is not None and len(hits) >= limits.max_matches:
            warnings.append("Truncated results due to match limit")
            break

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return SearchTextResponse(
        ok=True,
        data=SearchTextData(hits=hits, total=result.total),
        warnings=warnings,
        metrics={"elapsed_ms": elapsed_ms},
        error=None,
    )
