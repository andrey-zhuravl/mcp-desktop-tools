"""Implementation of the search_text MCP tool with caching and profiling."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import logging
import time

from ..adapters.rg import RipgrepRequest, RipgrepNotFoundError, run_ripgrep
from ..cache import (
    build_cache_key,
    ensure_entry_within_limit,
    get_cache_settings,
    get_search_cache,
)
from ..config import WorkspacesConfig, ensure_tool_allowed
from ..metrics import ProfileCollector, add_profile
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
    disable_cache: bool = False
    profile: bool = False

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
            disable_cache=bool(data.get("disable_cache", False)),
            profile=bool(data.get("profile", False)),
        )


@dataclass
class SearchHit:
    file: str
    line: int
    text: str
    abs_path: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "SearchHit":
        return cls(
            file=str(payload.get("file", "")),
            line=int(payload.get("line", 0)),
            text=str(payload.get("text", "")),
            abs_path=payload.get("abs_path") if isinstance(payload.get("abs_path"), str) else None,
        )


@dataclass
class SearchTextData:
    hits: List[SearchHit] = field(default_factory=list)
    total: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "hits": [hit.__dict__ for hit in self.hits],
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "SearchTextData":
        hits_raw = payload.get("hits")
        hits: List[SearchHit] = []
        if isinstance(hits_raw, list):
            for item in hits_raw:
                if isinstance(item, dict):
                    hits.append(SearchHit.from_dict(item))
        total_value = payload.get("total")
        try:
            total_int = int(total_value) if total_value is not None else 0
        except (TypeError, ValueError):
            total_int = 0
        return cls(hits=hits, total=total_int)


@dataclass
class SearchTextResponse:
    ok: bool
    data: SearchTextData
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
    def from_dict(cls, payload: Dict[str, object]) -> "SearchTextResponse":
        data_obj = SearchTextData.from_dict(payload.get("data", {}) if isinstance(payload.get("data"), dict) else {})
        warnings = payload.get("warnings")
        metrics = payload.get("metrics")
        error = payload.get("error")
        return cls(
            ok=bool(payload.get("ok", False)),
            data=data_obj,
            warnings=list(warnings) if isinstance(warnings, list) else [],
            metrics=dict(metrics) if isinstance(metrics, dict) else {},
            error=dict(error) if isinstance(error, dict) else None,
        )


def _estimate_hit_size(hit: SearchHit) -> int:
    return sum(len(str(value).encode("utf-8")) for value in (hit.file, hit.text, hit.abs_path or "")) + 32


def execute(request: SearchTextRequest, config: WorkspacesConfig) -> SearchTextResponse:
    start = time.perf_counter()
    profile = ProfileCollector(request.profile)
    cache_settings = get_cache_settings()
    cache_key: Optional[str] = None

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

    with profile.stage("build_args"):
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
            timeout_ms=config.env.subprocess_timeout_ms,
        )

    cache_parts = (
        "search_text",
        request.workspace_id,
        str(validation.path),
        request.query,
        request.regex,
        request.case_sensitive,
        tuple(sorted(request.include_globs)),
        tuple(sorted(exclude_globs)),
        request.max_matches,
        request.before,
        request.after,
        effective_depth,
    )
    cache_key = build_cache_key(cache_parts)

    if not request.disable_cache:
        search_cache = get_search_cache()
        if search_cache is not None:
            cached_payload = search_cache.get(cache_key)
            if cached_payload is not None:
                cached_response = SearchTextResponse.from_dict(cached_payload)
                metrics = dict(cached_response.metrics)
                metrics.update(
                    {
                        "elapsed_ms": int((time.perf_counter() - start) * 1000),
                        "cache_hit": True,
                        "cache_key": cache_key,
                    }
                )
                metrics = add_profile(metrics, profile)
                cached_response.metrics = metrics
                return cached_response

    try:
        with profile.stage("run_rg"):
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
    except TimeoutError:
        LOGGER.error("Ripgrep timed out for workspace %s", workspace.id)
        return SearchTextResponse(
            ok=False,
            data=SearchTextData(),
            warnings=["ripgrep timed out"],
            metrics={"elapsed_ms": int((time.perf_counter() - start) * 1000)},
            error={"type": "timeout", "message": "ripgrep invocation exceeded timeout"},
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

    with profile.stage("parse"):
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
                abs_path=str(hit.file.resolve(strict=False))
                if hit.file.is_absolute()
                else str((workspace.path / hit.file).resolve(strict=False)),
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

    metrics: Dict[str, object] = {
        "elapsed_ms": elapsed_ms,
        "rg_elapsed_ms": result.elapsed_ms,
        "cache_hit": False,
    }
    if cache_key:
        metrics["cache_key"] = cache_key
    metrics = add_profile(metrics, profile)

    response = SearchTextResponse(
        ok=True,
        data=SearchTextData(hits=hits, total=result.total),
        warnings=warnings,
        metrics=metrics,
        error=None,
    )

    if cache_key and not request.disable_cache:
        search_cache = get_search_cache()
        if search_cache is not None:
            payload = response.to_dict()
            if ensure_entry_within_limit(payload, max_bytes=cache_settings.max_entry_bytes):
                search_cache[cache_key] = payload

    return response

