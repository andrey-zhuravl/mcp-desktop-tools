"""Implementation of the git_graph MCP tool."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import logging
import time

from ..adapters.git import (
    AuthorStat,
    BranchInfo,
    CommitInfo,
    GitError,
    GitNotFoundError,
    get_author_stats,
    get_last_commits,
    get_repo_root,
    list_branches,
    measure_git,
)
from ..config import WorkspacesConfig, ensure_tool_allowed
from ..security import normalize_workspace_path

LOGGER = logging.getLogger(__name__)
TOOL_NAME = "git_graph"
HARD_LAST_COMMITS_LIMIT = 200


@dataclass
class GitGraphRequest:
    workspace_id: str
    rel_path: str
    last_commits: Optional[int] = None
    with_files: bool = False
    authors_stats: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "GitGraphRequest":
        if "workspace_id" not in data:
            raise ValueError("workspace_id is required")
        if "rel_path" not in data:
            raise ValueError("rel_path is required")
        return cls(
            workspace_id=str(data["workspace_id"]),
            rel_path=str(data["rel_path"]),
            last_commits=int(data["last_commits"]) if data.get("last_commits") is not None else None,
            with_files=bool(data.get("with_files", False)),
            authors_stats=bool(data.get("authors_stats", True)),
        )


@dataclass
class GitGraphData:
    repo_root: str
    branches: List[BranchInfo]
    last_commits: List[CommitInfo]
    authors: List[AuthorStat] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "repo_root": self.repo_root,
            "branches": [branch.__dict__ for branch in self.branches],
            "last_commits": [
                {
                    **commit.__dict__,
                    "files": [file.__dict__ for file in commit.files] if commit.files else None,
                }
                for commit in self.last_commits
            ],
            "authors": [author.__dict__ for author in self.authors],
        }


@dataclass
class GitGraphResponse:
    ok: bool
    data: GitGraphData
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


def _clamp_last_commits(requested: Optional[int], limit: int, warnings: List[str]) -> int:
    if requested is None:
        return limit
    if requested > HARD_LAST_COMMITS_LIMIT:
        warnings.append(
            f"Requested last_commits={requested} exceeds hard limit {HARD_LAST_COMMITS_LIMIT}; using {HARD_LAST_COMMITS_LIMIT}"
        )
        return HARD_LAST_COMMITS_LIMIT
    if requested > limit:
        warnings.append(f"Requested last_commits={requested} exceeds configured limit {limit}; using {limit}")
        return limit
    return max(0, requested)


def execute(request: GitGraphRequest, config: WorkspacesConfig) -> GitGraphResponse:
    start = time.perf_counter()
    warnings: List[str] = []

    try:
        workspace = config.get_workspace(request.workspace_id)
    except KeyError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return GitGraphResponse(
            ok=False,
            data=GitGraphData(repo_root="", branches=[], last_commits=[]),
            warnings=[],
            metrics={"elapsed_ms": elapsed},
            error={"type": "workspace_not_found", "message": str(exc)},
        )

    try:
        ensure_tool_allowed(workspace, TOOL_NAME)
    except PermissionError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return GitGraphResponse(
            ok=False,
            data=GitGraphData(repo_root="", branches=[], last_commits=[]),
            warnings=["Tool is not allowed for this workspace"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "tool_not_allowed", "message": str(exc)},
        )

    validation = normalize_workspace_path(workspace.path, Path(request.rel_path))
    if not validation.ok or validation.path is None:
        elapsed = int((time.perf_counter() - start) * 1000)
        reason = validation.reason or "Invalid path"
        return GitGraphResponse(
            ok=False,
            data=GitGraphData(repo_root="", branches=[], last_commits=[]),
            warnings=[reason],
            metrics={"elapsed_ms": elapsed},
            error={"type": "path_error", "message": reason},
        )

    git_path = config.env.git_path or "git"

    effective_last_commits = _clamp_last_commits(
        request.last_commits, config.limits.git_last_commits, warnings
    )

    if request.with_files and effective_last_commits > 50:
        warnings.append("with_files=true with large last_commits may be slow")

    git_elapsed = 0

    try:
        repo_root, elapsed_git = measure_git(get_repo_root, validation.path, git_path=git_path)
        git_elapsed += elapsed_git
    except GitNotFoundError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return GitGraphResponse(
            ok=False,
            data=GitGraphData(repo_root="", branches=[], last_commits=[]),
            warnings=["git binary not found"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "missing_dependency", "message": str(exc)},
        )
    except GitError as exc:
        elapsed = int((time.perf_counter() - start) * 1000)
        return GitGraphResponse(
            ok=False,
            data=GitGraphData(repo_root="", branches=[], last_commits=[]),
            warnings=["Failed to locate git repository"],
            metrics={"elapsed_ms": elapsed},
            error={"type": "execution_error", "message": str(exc)},
        )

    try:
        branches, elapsed_branch = measure_git(list_branches, repo_root, git_path=git_path)
        git_elapsed += elapsed_branch
    except GitError as exc:
        warnings.append(f"Failed to list branches: {exc}")
        branches = []

    try:
        commits, elapsed_commits = measure_git(
            get_last_commits,
            repo_root,
            git_path=git_path,
            max_count=effective_last_commits,
            with_files=request.with_files,
        )
        git_elapsed += elapsed_commits
    except GitError as exc:
        warnings.append(f"Failed to retrieve commits: {exc}")
        commits = []

    authors: List[AuthorStat] = []
    if request.authors_stats:
        try:
            authors_stats, elapsed_authors = measure_git(get_author_stats, repo_root, git_path=git_path)
            authors = authors_stats
            git_elapsed += elapsed_authors
        except GitError as exc:
            warnings.append(f"Failed to compute author stats: {exc}")

    elapsed_total = int((time.perf_counter() - start) * 1000)

    data = GitGraphData(
        repo_root=str(repo_root),
        branches=branches,
        last_commits=commits,
        authors=authors,
    )

    metrics = {"elapsed_ms": elapsed_total}
    if git_elapsed:
        metrics["git_cmd_ms"] = git_elapsed

    return GitGraphResponse(ok=True, data=data, warnings=warnings, metrics=metrics)
