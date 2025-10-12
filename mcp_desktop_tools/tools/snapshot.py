"""Composite snapshot MCP tool combining git, filesystem, and environment metadata."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging
import os
import platform
import shutil
import subprocess
import time

try:  # Optional dependency
    import mlflow
    from mlflow import tracking as mlflow_tracking
except Exception:  # pragma: no cover - mlflow is optional at runtime
    mlflow = None  # type: ignore
    mlflow_tracking = None  # type: ignore

from .. import __version__
from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import normalize_workspace_path
from .git_graph import GitGraphRequest, GitGraphResponse, execute as execute_git_graph
from .repo_map import RepoMapRequest, RepoMapResponse, execute as execute_repo_map

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "snapshot"
ENV_INCLUDE_FLAG = "MCPDT_SNAPSHOT_INCLUDE_ENV"
DEFAULT_ARTIFACT_NAME = "repo_snapshot.json"
DEFAULT_EXPERIMENT = "mcp-desktop-tools"


@dataclass
class SnapshotRequest:
    workspace_id: str
    rel_path: str
    include_git: bool = True
    include_fs: bool = True
    include_env: bool = True
    largest_files: int = 50
    mlflow_logging: bool = False
    mlflow_uri: Optional[str] = None
    experiment: Optional[str] = None
    run_name: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    artifact_path: str = DEFAULT_ARTIFACT_NAME

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "SnapshotRequest":
        if "workspace_id" not in data:
            raise ValueError("workspace_id is required")
        if "rel_path" not in data:
            raise ValueError("rel_path is required")
        tags_raw = data.get("tags") or {}
        if not isinstance(tags_raw, dict):
            raise ValueError("tags must be a mapping of string keys to string values")
        tags: Dict[str, str] = {str(key): str(value) for key, value in tags_raw.items()}
        return cls(
            workspace_id=str(data["workspace_id"]),
            rel_path=str(data["rel_path"]),
            include_git=bool(data.get("include_git", True)),
            include_fs=bool(data.get("include_fs", True)),
            include_env=bool(data.get("include_env", True)),
            largest_files=int(data.get("largest_files", 50)),
            mlflow_logging=bool(data.get("mlflow_logging", False)),
            mlflow_uri=str(data.get("mlflow_uri")) if data.get("mlflow_uri") is not None else None,
            experiment=str(data.get("experiment")) if data.get("experiment") is not None else None,
            run_name=str(data.get("run_name")) if data.get("run_name") is not None else None,
            tags=tags,
            artifact_path=str(data.get("artifact_path", DEFAULT_ARTIFACT_NAME)),
        )


@dataclass
class SnapshotData:
    snapshot: Dict[str, object]
    artifact: Optional[str] = None
    mlflow: Optional[Dict[str, str]] = None


@dataclass
class SnapshotResponse:
    ok: bool
    data: SnapshotData
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)
    error: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, object]:
        payload: Dict[str, object] = {
            "ok": self.ok,
            "data": {
                "snapshot": self.data.snapshot,
            },
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
        }
        if self.data.artifact is not None:
            payload["data"]["artifact"] = self.data.artifact
        if self.data.mlflow is not None:
            payload["data"]["mlflow"] = self.data.mlflow
        if self.error is not None:
            payload["error"] = dict(self.error)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "SnapshotResponse":  # pragma: no cover - convenience helper
        data = payload.get("data")
        snapshot_data: Dict[str, object] = {}
        artifact: Optional[str] = None
        mlflow_info: Optional[Dict[str, str]] = None
        if isinstance(data, dict):
            snapshot_payload = data.get("snapshot")
            if isinstance(snapshot_payload, dict):
                snapshot_data = snapshot_payload
            artifact_payload = data.get("artifact")
            if isinstance(artifact_payload, str):
                artifact = artifact_payload
            mlflow_payload = data.get("mlflow")
            if isinstance(mlflow_payload, dict):
                mlflow_info = {str(key): str(value) for key, value in mlflow_payload.items()}
        return cls(
            ok=bool(payload.get("ok", False)),
            data=SnapshotData(snapshot=snapshot_data, artifact=artifact, mlflow=mlflow_info),
            warnings=list(payload.get("warnings", [])) if isinstance(payload.get("warnings"), list) else [],
            metrics=dict(payload.get("metrics", {})) if isinstance(payload.get("metrics"), dict) else {},
            error=dict(payload.get("error", {})) if isinstance(payload.get("error"), dict) else None,
        )


def _serialize_size_bytes(payload: Dict[str, object]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _truncate_for_limit(snapshot: Dict[str, object], limit: int, warnings: List[str]) -> int:
    size = _serialize_size_bytes(snapshot)
    if size <= limit:
        return size
    truncated = False

    fs_section = snapshot.get("fs")
    if isinstance(fs_section, dict):
        if fs_section.get("largest_files"):
            fs_section["largest_files"] = []
            warnings.append("Dropped fs.largest_files to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
        if size > limit and fs_section.get("top"):
            fs_section["top"] = []
            warnings.append("Dropped fs.top to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
        if size > limit and fs_section.get("extensions"):
            fs_section["extensions"] = {}
            warnings.append("Dropped fs.extensions to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
        if size > limit and fs_section.get("languages"):
            fs_section["languages"] = {}
            warnings.append("Dropped fs.languages to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
    git_section = snapshot.get("git")
    if size > limit and isinstance(git_section, dict):
        commits = git_section.get("last_commits")
        if isinstance(commits, list) and commits:
            git_section["last_commits"] = commits[:1]
            warnings.append("Truncated git.last_commits to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
        authors = git_section.get("authors")
        if size > limit and isinstance(authors, list) and authors:
            git_section["authors"] = []
            warnings.append("Dropped git.authors to satisfy max_output_bytes")
            truncated = True
            size = _serialize_size_bytes(snapshot)
    if size > limit:
        snapshot["truncated"] = True
        warnings.append("Snapshot truncated after exhausting section reductions")
        truncated = True
        size = _serialize_size_bytes(snapshot)
    if truncated and "truncated" not in snapshot:
        snapshot["truncated"] = True
    return size


def _collect_tool_versions(config: WorkspacesConfig) -> Dict[str, str]:
    versions: Dict[str, str] = {"mcp-desktop-tools": __version__}
    binaries = {
        "rg": config.env.rg_path or shutil.which("rg"),
        "git": config.env.git_path or shutil.which("git"),
    }
    for name, path in binaries.items():
        if not path:
            continue
        try:
            result = subprocess.run(
                [path, "--version"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        output = result.stdout.strip() or result.stderr.strip()
        if output:
            first_line = output.splitlines()[0].strip()
            versions[name] = first_line
    return versions


def _collect_env_info(config: WorkspacesConfig) -> Dict[str, object]:
    info: Dict[str, object] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
    }
    tools = _collect_tool_versions(config)
    if tools:
        info["tools"] = tools
    return info


def _write_artifact(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _prepare_git_section(response: GitGraphResponse, warnings: List[str]) -> Optional[Dict[str, object]]:
    if not response.ok:
        message = response.error.get("message") if response.error else "git_graph failed"
        warnings.append(f"git_graph error: {message}")
        return None
    payload = response.data.to_dict()
    branches = payload.get("branches")
    branch_name = None
    if isinstance(branches, list):
        for branch in branches:
            if isinstance(branch, dict) and branch.get("is_current"):
                branch_name = branch.get("name")
                break
    commits = payload.get("last_commits")
    head = None
    if isinstance(commits, list) and commits:
        first = commits[0]
        if isinstance(first, dict):
            head = first.get("hash")
    git_section: Dict[str, object] = {
        "branch": branch_name,
        "head": head,
        "branches": branches or [],
        "last_commits": commits or [],
        "authors": payload.get("authors") or [],
    }
    return git_section


def _prepare_fs_section(response: RepoMapResponse, largest_limit: int, warnings: List[str]) -> Optional[Dict[str, object]]:
    if not response.ok:
        message = response.error.get("message") if response.error else "repo_map failed"
        warnings.append(f"repo_map error: {message}")
        return None
    payload = response.data.to_dict()
    largest = payload.get("largest_files")
    if isinstance(largest, list) and largest_limit >= 0:
        if len(largest) > largest_limit:
            warnings.append(
                f"Truncated largest_files to {largest_limit} entries (was {len(largest)})"
            )
            payload["largest_files"] = largest[:largest_limit]
    return payload


def _log_to_mlflow(
    request: SnapshotRequest,
    snapshot: Dict[str, object],
    warnings: List[str],
) -> Optional[Dict[str, str]]:
    if not request.mlflow_logging:
        return None
    if mlflow is None or mlflow_tracking is None:
        warnings.append("mlflow not available; skipping MLflow logging")
        return None
    tracking_uri = request.mlflow_uri or os.environ.get("MLFLOW_TRACKING_URI")
    if not tracking_uri:
        warnings.append("MLflow logging requested but no tracking URI provided")
        return None
    experiment_name = request.experiment or os.environ.get("MLFLOW_EXPERIMENT_NAME") or DEFAULT_EXPERIMENT

    try:
        mlflow.set_tracking_uri(tracking_uri)
        experiment = mlflow.set_experiment(experiment_name)
    except Exception as exc:  # pragma: no cover - depends on mlflow backend
        warnings.append(f"Failed to set MLflow experiment: {exc}")
        return None

    run = None
    try:
        run = mlflow.start_run(run_name=request.run_name)
        tags = {
            "workspace_id": request.workspace_id,
            "snapshot.generated_at": str(snapshot.get("generated_at")),
            "snapshot.repo_root": str(snapshot.get("repo_root")),
        }
        for key, value in request.tags.items():
            tags[str(key)] = str(value)
        mlflow.set_tags(tags)
        mlflow.log_dict(snapshot, artifact_file=request.artifact_path or DEFAULT_ARTIFACT_NAME)
        active = mlflow.active_run()
        if not active:
            return None
        info = {
            "tracking_uri": tracking_uri,
            "experiment_id": experiment.experiment_id if experiment else "",
            "run_id": active.info.run_id,
        }
        return info
    except Exception as exc:  # pragma: no cover - depends on mlflow backend
        warnings.append(f"Failed to log snapshot to MLflow: {exc}")
        return None
    finally:
        if run is not None:
            try:
                mlflow.end_run()
            except Exception:  # pragma: no cover - defensive cleanup
                LOGGER.debug("Failed to end MLflow run", exc_info=True)


def execute(request: SnapshotRequest, config: WorkspacesConfig) -> SnapshotResponse:
    start = time.perf_counter()
    warnings: List[str] = []

    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        data = SnapshotData(snapshot={})
        return SnapshotResponse(
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
        data = SnapshotData(snapshot={})
        return SnapshotResponse(
            ok=False,
            data=data,
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.rel_path))
    if not validation.ok or validation.path is None:
        elapsed = int((time.perf_counter() - start) * 1000)
        reason = validation.reason or "Invalid path"
        data = SnapshotData(snapshot={})
        return SnapshotResponse(
            ok=False,
            data=data,
            warnings=[reason],
            metrics={"elapsed_ms": elapsed},
            error={"type": "path_error", "message": reason},
        )

    target_path = validation.path
    snapshot: Dict[str, object] = {
        "workspace_id": request.workspace_id,
        "repo_root": str(target_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    git_metrics: Dict[str, object] = {}
    if request.include_git:
        git_request = GitGraphRequest(
            workspace_id=request.workspace_id,
            rel_path=request.rel_path,
        )
        git_response = execute_git_graph(git_request, config)
        git_section = _prepare_git_section(git_response, warnings)
        if git_section is not None:
            snapshot["git"] = git_section
        git_metrics = git_response.metrics
        warnings.extend(git_response.warnings)

    fs_metrics: Dict[str, object] = {}
    if request.include_fs:
        repo_request = RepoMapRequest(
            workspace_id=request.workspace_id,
            rel_path=request.rel_path,
        )
        repo_response = execute_repo_map(repo_request, config)
        fs_section = _prepare_fs_section(repo_response, max(request.largest_files, 0), warnings)
        if fs_section is not None:
            snapshot["fs"] = fs_section
        fs_metrics = repo_response.metrics
        warnings.extend(repo_response.warnings)

    include_env = request.include_env and os.environ.get(ENV_INCLUDE_FLAG) == "1"
    if request.include_env and not include_env:
        warnings.append("Environment section skipped (set MCPDT_SNAPSHOT_INCLUDE_ENV=1 to enable)")
    if include_env:
        snapshot["env"] = _collect_env_info(config)

    size_bytes = _serialize_size_bytes(snapshot)
    limit = config.limits.max_output_bytes
    if size_bytes > limit:
        size_bytes = _truncate_for_limit(snapshot, limit, warnings)

    artifact_path = Path(request.artifact_path)
    if not artifact_path.is_absolute():
        artifact_path = Path.cwd() / artifact_path

    try:
        _write_artifact(artifact_path, snapshot)
        artifact_str = str(artifact_path)
    except OSError as exc:
        warnings.append(f"Failed to write artifact: {exc}")
        artifact_str = None

    mlflow_info = _log_to_mlflow(request, snapshot, warnings)

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    metrics: Dict[str, object] = {
        "elapsed_ms": elapsed_ms,
        "bytes_serialized": size_bytes,
    }
    git_elapsed = git_metrics.get("git_cmd_ms")
    if git_elapsed is not None:
        metrics["git_cmd_ms"] = git_elapsed
    fs_walk = fs_metrics.get("fs_walk_count")
    if fs_walk is not None:
        metrics["fs_walk_count"] = fs_walk

    data = SnapshotData(snapshot=snapshot, artifact=artifact_str, mlflow=mlflow_info)
    response = SnapshotResponse(ok=True, data=data, warnings=warnings, metrics=metrics)
    return response
