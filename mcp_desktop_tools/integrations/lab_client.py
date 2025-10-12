"""Helper client for invoking MCP Desktop Tools from *Lab Python agents."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import WorkspacesConfig, load_workspaces
from ..tools.snapshot import SnapshotRequest, SnapshotResponse, execute as execute_snapshot


@dataclass
class LabClient:
    """Lightweight helper that wires workspaces to high-level tool calls."""

    workspace_id: str
    config: WorkspacesConfig

    @classmethod
    def from_config_path(cls, workspace_id: str, config_path: Optional[Path] = None) -> "LabClient":
        """Instantiate a client by loading `workspaces.yaml` from a specific location."""
        return cls(workspace_id=workspace_id, config=load_workspaces(config_path))

    @classmethod
    def auto(cls, workspace_id: str) -> "LabClient":
        """Instantiate a client using the default configuration resolution rules."""
        return cls(workspace_id=workspace_id, config=load_workspaces())

    def snapshot(self, rel_path: str = ".", **overrides) -> SnapshotResponse:
        """Execute the snapshot tool and return its structured response."""
        request_dict = {"workspace_id": self.workspace_id, "rel_path": rel_path}
        request_dict.update(overrides)
        request = SnapshotRequest.from_dict(request_dict)
        return execute_snapshot(request, self.config)
