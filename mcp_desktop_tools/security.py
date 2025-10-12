"""Security helpers for MCP Desktop Tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
import logging

from .config import LimitsConfig, Workspace

LOGGER = logging.getLogger(__name__)


@dataclass
class PathValidationResult:
    ok: bool
    path: Optional[Path] = None
    reason: Optional[str] = None


def _detect_symlink_escape(candidate: Path, workspace_root: Path) -> bool:
    """Return True if any symlink in the path escapes the workspace."""
    workspace_root = workspace_root.resolve()
    current = candidate
    try:
        while True:
            if current == workspace_root or current.parent == current:
                break
            if current.exists() and current.is_symlink():
                target = current.resolve(strict=False)
                if not _is_relative_to(target, workspace_root):
                    return True
            current = current.parent
    except OSError:
        return True
    return False


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
        return True
    except ValueError:
        return False


def path_in_workspace(workspace_path: Path, candidate: Path, *, follow_symlinks: bool = False) -> bool:
    """Check whether *candidate* is inside *workspace_path* respecting symlink policy."""
    workspace_root = Path(workspace_path).resolve()
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        candidate_path = workspace_root / candidate_path

    try:
        resolved = candidate_path.resolve(strict=False)
    except OSError:
        resolved = (candidate_path.parent.resolve(strict=False) / candidate_path.name)

    if not _is_relative_to(resolved, workspace_root):
        return False

    if not follow_symlinks and _detect_symlink_escape(candidate_path, workspace_root):
        return False

    return True


def normalize_workspace_path(workspace_path: Path, rel_path: Optional[Path]) -> PathValidationResult:
    workspace_root = Path(workspace_path).resolve()
    if rel_path is None:
        return PathValidationResult(ok=True, path=workspace_root)

    candidate = Path(rel_path)
    if candidate.is_absolute() and not _is_relative_to(candidate, workspace_root):
        return PathValidationResult(ok=False, reason="Absolute path outside workspace")

    if not path_in_workspace(workspace_root, candidate):
        return PathValidationResult(ok=False, reason="Path escapes workspace")

    return PathValidationResult(ok=True, path=(workspace_root / candidate).resolve())


def clamp_depth(requested: Optional[int], workspace_max: Optional[int]) -> Optional[int]:
    if requested is None:
        return workspace_max
    if workspace_max is None:
        return requested
    return min(requested, workspace_max)


def clamp_limits(global_limits: LimitsConfig, *, max_matches: Optional[int] = None,
                 max_output_bytes: Optional[int] = None, max_file_size_bytes: Optional[int] = None) -> LimitsConfig:
    return global_limits.merge(
        max_matches=max_matches,
        max_output_bytes=max_output_bytes,
        max_file_size_bytes=max_file_size_bytes,
    )


def merge_excludes(workspace: Workspace, request_excludes: Optional[Iterable[str]]) -> List[str]:
    excludes = list(workspace.excludes)
    if request_excludes:
        excludes.extend(request_excludes)
    return excludes
