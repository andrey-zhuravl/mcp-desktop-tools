"""Lightweight filesystem watchers orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
import logging
import os

LOGGER = logging.getLogger(__name__)


@dataclass
class WatchersConfig:
    enabled: bool = False
    backend: str = "auto"
    debounce_ms: int = 200
    max_batch: int = 512
    index_path: Path = Path.home() / ".mcpdt" / "recent_index"
    rebuild_on_start: bool = False


@dataclass
class WatcherStatus:
    enabled: bool
    backend: str
    watchers_count: int
    queued_events: int
    last_event_ts: Optional[str]


@dataclass
class WatcherWorkspace:
    workspace_id: str
    watchers_count: int = 0
    queued_events: int = 0
    last_event_ts: Optional[datetime] = None

    def bump_event(self) -> None:
        self.queued_events += 1
        self.last_event_ts = datetime.utcnow()


@dataclass
class ReindexResult:
    reindexed: bool
    invalidated: list[str] = field(default_factory=list)


class WatchersEngine:
    """Simplified watcher engine used for introspection and CLI wiring."""

    def __init__(self, config: Optional[WatchersConfig] = None):
        self._config = config or load_watchers_config()
        self._workspaces: Dict[str, WatcherWorkspace] = {}

    @property
    def config(self) -> WatchersConfig:
        return self._config

    def ensure_workspace(self, workspace_id: str) -> WatcherWorkspace:
        workspace = self._workspaces.get(workspace_id)
        if not workspace:
            workspace = WatcherWorkspace(workspace_id=workspace_id)
            if self._config.enabled:
                workspace.watchers_count = 1
            self._workspaces[workspace_id] = workspace
        return workspace

    def status(self, workspace_id: str) -> WatcherStatus:
        workspace = self.ensure_workspace(workspace_id)
        ts = workspace.last_event_ts.isoformat() if workspace.last_event_ts else None
        return WatcherStatus(
            enabled=self._config.enabled,
            backend=self._config.backend,
            watchers_count=workspace.watchers_count,
            queued_events=workspace.queued_events,
            last_event_ts=ts,
        )

    def mark_event(self, workspace_id: str) -> None:
        workspace = self.ensure_workspace(workspace_id)
        workspace.bump_event()

    def reindex(self, workspace_id: str, rel_path: Optional[str] = None) -> ReindexResult:
        workspace = self.ensure_workspace(workspace_id)
        workspace.queued_events = 0
        workspace.last_event_ts = datetime.utcnow()
        invalidated = [rel_path] if rel_path else []
        return ReindexResult(reindexed=True, invalidated=invalidated)


def load_watchers_config() -> WatchersConfig:
    enabled = os.environ.get("MCPDT_WATCHERS_ENABLED") == "1"
    backend = os.environ.get("MCPDT_WATCHERS_BACKEND", "auto")
    debounce = int(os.environ.get("MCPDT_WATCHERS_DEBOUNCE_MS", "200"))
    max_batch = int(os.environ.get("MCPDT_WATCHERS_MAX_BATCH", "512"))
    index_path = Path(os.environ.get("MCPDT_RECENT_INDEX_PATH", Path.home() / ".mcpdt" / "recent_index"))
    rebuild = os.environ.get("MCPDT_WATCHERS_REBUILD_ON_START", "0") == "1"
    return WatchersConfig(
        enabled=enabled,
        backend=backend,
        debounce_ms=debounce,
        max_batch=max_batch,
        index_path=index_path,
        rebuild_on_start=rebuild,
    )


ENGINE = WatchersEngine()


def get_engine() -> WatchersEngine:
    return ENGINE
