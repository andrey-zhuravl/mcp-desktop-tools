"""MCP tools for plugin and watcher introspection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time

from ..plugins import get_plugin_manager
from ..plugins.loader import PluginRecord, PluginStatus
from ..watchers import get_engine


@dataclass
class PluginsListRequest:
    filter: Optional[str] = None


@dataclass
class PluginsListItem:
    id: str
    name: str
    version: str
    entry: str
    capabilities: List[str]
    tools: List[str] = field(default_factory=list)
    status: str = "loaded"
    reason: Optional[str] = None

    @classmethod
    def from_record(cls, record: PluginRecord) -> "PluginsListItem":
        manifest = record.manifest
        return cls(
            id=manifest.id if manifest else record.source or "unknown",
            name=manifest.name if manifest else "<invalid>",
            version=manifest.version if manifest else "0.0.0",
            entry=manifest.entry if manifest else "<unknown>",
            capabilities=list(manifest.capabilities) if manifest else [],
            tools=list(record.tools.keys()),
            status=record.status.value,
            reason=record.reason,
        )


@dataclass
class PluginsListResponse:
    ok: bool
    data: Dict[str, object]
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "data": self.data,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


@dataclass
class PluginInfoRequest:
    plugin_id: str


@dataclass
class PluginInfoResponse:
    ok: bool
    data: Dict[str, object]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "data": self.data,
            "warnings": self.warnings,
        }


@dataclass
class WatchersStatusRequest:
    workspace_id: str


@dataclass
class WatchersStatusResponse:
    ok: bool
    data: Dict[str, object]
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "data": self.data,
            "warnings": self.warnings,
            "metrics": self.metrics,
        }


@dataclass
class WatchersReindexRequest:
    workspace_id: str
    rel_path: Optional[str] = None


@dataclass
class WatchersReindexResponse:
    ok: bool
    data: Dict[str, object]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "data": self.data,
            "warnings": self.warnings,
        }


def plugins_list(request: PluginsListRequest) -> PluginsListResponse:
    manager = get_plugin_manager()
    start = time.perf_counter()
    records = manager.load_all().values()
    items = [PluginsListItem.from_record(record) for record in records]
    if request.filter:
        needle = request.filter.lower()
        items = [item for item in items if needle in item.id.lower() or needle in item.name.lower()]
    data = {
        "plugins": [item.__dict__ for item in items],
    }
    metrics = {
        "elapsed_ms": int((time.perf_counter() - start) * 1000),
        "plugins_loaded": sum(1 for item in items if item.status == PluginStatus.LOADED.value),
        "plugins_blocked": sum(1 for item in items if item.status == PluginStatus.BLOCKED.value),
    }
    return PluginsListResponse(ok=True, data=data, metrics=metrics)


def plugin_info(request: PluginInfoRequest) -> PluginInfoResponse:
    manager = get_plugin_manager()
    record = manager.get_plugin(request.plugin_id)
    if not record:
        return PluginInfoResponse(ok=False, data={}, warnings=[f"Plugin {request.plugin_id} not found"])
    manifest = record.manifest
    data = {
        "manifest": manifest.__dict__ if manifest else None,
        "tools": list(record.tools.keys()),
        "status": record.status.value,
        "reason": record.reason,
    }
    return PluginInfoResponse(ok=True, data=data)


def watchers_status(request: WatchersStatusRequest) -> WatchersStatusResponse:
    start = time.perf_counter()
    engine = get_engine()
    status = engine.status(request.workspace_id)
    data = {
        "enabled": status.enabled,
        "backend": status.backend,
        "watchers_count": status.watchers_count,
        "queued_events": status.queued_events,
        "last_event_ts": status.last_event_ts,
    }
    metrics = {"elapsed_ms": int((time.perf_counter() - start) * 1000)}
    return WatchersStatusResponse(ok=True, data=data, metrics=metrics)


def watchers_reindex(request: WatchersReindexRequest) -> WatchersReindexResponse:
    engine = get_engine()
    result = engine.reindex(request.workspace_id, rel_path=request.rel_path)
    data = {
        "reindexed": result.reindexed,
        "invalidated": result.invalidated,
    }
    return WatchersReindexResponse(ok=True, data=data)
