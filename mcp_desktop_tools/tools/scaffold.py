"""Scaffold tool implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import logging
import stat
import time

from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import normalize_workspace_path, path_in_workspace
from ..templates import TemplateRegistry, TemplateRegistryError, load_registry

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "scaffold"


class ScaffoldError(RuntimeError):
    """Raised when scaffold processing fails."""


@dataclass
class InlineFile:
    path: str
    content: str
    executable: bool = False


@dataclass
class ScaffoldRequest:
    workspace_id: str
    target_rel: str
    template_id: Optional[str] = None
    inline_spec: Optional[Dict[str, object]] = None
    vars: Dict[str, str] = field(default_factory=dict)
    dry_run: bool = True
    overwrite: bool = False
    select: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ScaffoldRequest":
        if "workspace_id" not in data or "target_rel" not in data:
            raise ValueError("workspace_id and target_rel are required")
        template_id = data.get("template_id")
        inline_spec = data.get("inline_spec")
        if template_id is None and inline_spec is None:
            raise ValueError("Either template_id or inline_spec must be provided")
        if template_id is not None and inline_spec is not None:
            raise ValueError("template_id and inline_spec are mutually exclusive")

        vars_raw = data.get("vars", {})
        if vars_raw is None:
            vars_dict: Dict[str, str] = {}
        elif isinstance(vars_raw, dict):
            vars_dict = {str(k): str(v) for k, v in vars_raw.items()}
        else:
            raise ValueError("vars must be a mapping")

        select_raw = data.get("select", [])
        if select_raw is None:
            select_list: List[str] = []
        elif isinstance(select_raw, list):
            select_list = [str(item) for item in select_raw]
        else:
            raise ValueError("select must be a list of strings")

        inline_payload: Optional[Dict[str, object]]
        if inline_spec is None:
            inline_payload = None
        elif isinstance(inline_spec, dict):
            inline_payload = inline_spec
        else:
            raise ValueError("inline_spec must be a mapping")

        return cls(
            workspace_id=str(data["workspace_id"]),
            target_rel=str(data["target_rel"]),
            template_id=str(template_id) if template_id is not None else None,
            inline_spec=inline_payload,
            vars=vars_dict,
            dry_run=bool(data.get("dry_run", True)),
            overwrite=bool(data.get("overwrite", False)),
            select=select_list,
        )


@dataclass
class PlannedOperation:
    op: str
    path: str


@dataclass
class ScaffoldStats:
    files_planned: int
    files_written: int
    bytes_written: int
    dry_run: bool


@dataclass
class ScaffoldData:
    planned: List[PlannedOperation] = field(default_factory=list)
    stats: ScaffoldStats = field(default_factory=lambda: ScaffoldStats(0, 0, 0, True))

    def to_dict(self) -> Dict[str, object]:
        return {
            "planned": [op.__dict__ for op in self.planned],
            "stats": self.stats.__dict__,
        }


@dataclass
class ScaffoldResponse:
    ok: bool
    data: ScaffoldData
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


def _parse_inline_files(inline_spec: Dict[str, object]) -> List[InlineFile]:
    files_raw = inline_spec.get("files")
    if not isinstance(files_raw, list) or not files_raw:
        raise ScaffoldError("inline_spec.files must be a non-empty list")
    files: List[InlineFile] = []
    for entry in files_raw:
        if not isinstance(entry, dict):
            raise ScaffoldError("inline_spec.files entries must be mappings")
        try:
            path = str(entry["path"])
            content = str(entry["content"])
        except KeyError as exc:
            raise ScaffoldError(f"Missing key in inline file specification: {exc.args[0]}") from exc
        executable = bool(entry.get("executable", False))
        files.append(InlineFile(path=path, content=content, executable=executable))
    return files


def _validate_relative_path(path: Path) -> None:
    if path.is_absolute():
        raise ScaffoldError("Destination path must be relative")
    if any(part == ".." for part in path.parts):
        raise ScaffoldError("Destination path cannot contain '..'")


def _ensure_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)


def _write_file(target: Path, content: str, *, executable: bool) -> None:
    target.write_text(content, encoding="utf-8")
    if executable:
        mode = target.stat().st_mode
        target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def execute(request: ScaffoldRequest, config: WorkspacesConfig, *, registry: Optional[TemplateRegistry] = None) -> ScaffoldResponse:
    start = time.perf_counter()
    data = ScaffoldData()
    warnings: List[str] = []

    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        LOGGER.error("Workspace not found: %s", request.workspace_id)
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "workspace_not_found", "message": str(exc)},
        )

    try:
        ensure_tool_allowed(workspace, TOOL_NAME)
    except PermissionError as exc:
        LOGGER.warning("Tool not allowed for workspace %s", workspace.id)
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.target_rel))
    if not validation.ok or validation.path is None:
        LOGGER.warning("Target path invalid for workspace %s: %s", workspace.id, validation.reason)
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=[validation.reason or "Invalid target path"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "path_error", "message": validation.reason or "Invalid target path"},
        )

    target_root = validation.path

    try:
        if request.template_id is not None:
            registry = registry or load_registry(config.env.templates_user_dir)
            template = registry.get(request.template_id)
            template_files = template.render(request.vars, select=request.select or None)
            files_to_process = [
                InlineFile(path=item.path, content=item.content, executable=item.executable)
                for item in template_files
            ]
        else:
            files_to_process = _parse_inline_files(request.inline_spec or {})
    except (KeyError, TemplateRegistryError, ScaffoldError) as exc:
        LOGGER.error("Failed to prepare scaffold content: %s", exc)
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "template_error", "message": str(exc)},
        )

    limit_files = getattr(config.limits, "scaffold_max_files", None)
    limit_bytes = getattr(config.limits, "scaffold_max_total_bytes", None)

    total_bytes = sum(len(file.content.encode("utf-8")) for file in files_to_process)
    if limit_files is not None and len(files_to_process) > limit_files:
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "limit_exceeded", "message": "Too many files requested"},
        )
    if limit_bytes is not None and total_bytes > limit_bytes:
        elapsed = int((time.perf_counter() - start) * 1000)
        return ScaffoldResponse(
            ok=False,
            data=data,
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "limit_exceeded", "message": "Total bytes exceed configured limit"},
        )

    files_written = 0
    bytes_written = 0

    for file in files_to_process:
        rel_path = Path(file.path)
        try:
            _validate_relative_path(rel_path)
        except ScaffoldError as exc:
            LOGGER.error("Invalid destination path %s: %s", file.path, exc)
            elapsed = int((time.perf_counter() - start) * 1000)
            return ScaffoldResponse(
                ok=False,
                data=data,
                warnings=[],
                metrics={"elapsed_ms": elapsed},
                error={"type": "path_error", "message": str(exc)},
            )

        absolute_path = target_root / rel_path
        if not path_in_workspace(workspace.path, absolute_path):
            LOGGER.error("Path %s escapes workspace %s", absolute_path, workspace.id)
            elapsed = int((time.perf_counter() - start) * 1000)
            return ScaffoldResponse(
                ok=False,
                data=data,
                warnings=[],
                metrics={"elapsed_ms": elapsed},
                error={"type": "path_error", "message": "Destination escapes workspace"},
            )

        if absolute_path.exists():
            if request.overwrite:
                op = "overwrite"
            else:
                op = "skip"
        else:
            op = "create"

        rel_to_workspace = absolute_path.relative_to(workspace.path)
        data.planned.append(PlannedOperation(op=op, path=str(rel_to_workspace.as_posix())))

        if op == "skip":
            warnings.append(f"Skipped existing file: {rel_to_workspace}")
            continue

        if not request.dry_run:
            _ensure_directory(absolute_path.parent)
            _write_file(absolute_path, file.content, executable=file.executable)
            files_written += 1
            bytes_written += len(file.content.encode("utf-8"))

    data.stats = ScaffoldStats(
        files_planned=len(data.planned),
        files_written=files_written,
        bytes_written=bytes_written,
        dry_run=request.dry_run,
    )

    elapsed = int((time.perf_counter() - start) * 1000)
    return ScaffoldResponse(
        ok=True,
        data=data,
        warnings=warnings,
        metrics={"elapsed_ms": elapsed},
    )


def execute_from_cli(args: Dict[str, object], config: WorkspacesConfig) -> ScaffoldResponse:
    request = ScaffoldRequest.from_dict(args)
    return execute(request, config)

