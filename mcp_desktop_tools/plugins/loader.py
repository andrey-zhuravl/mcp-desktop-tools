"""Plugin discovery and loading logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from importlib import import_module
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import logging
import os
import time

from .api import PluginAPI, PluginRegistrationError
from ..utils.yaml import load_yaml, YamlError

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "mcp_desktop_tools.plugins"
MANIFEST_FILENAME = "plugin.yaml"


class PluginStatus(str, Enum):
    """Lifecycle states for a plugin."""

    LOADED = "loaded"
    BLOCKED = "blocked"
    ERROR = "error"


class CapabilityError(RuntimeError):
    """Raised when a plugin manifest violates the security policy."""


@dataclass
class Manifest:
    """In-memory representation of a plugin manifest."""

    id: str
    name: str
    version: str
    entry: str
    capabilities: List[str]
    tools: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "Manifest":
        required_fields = ["id", "name", "version", "entry", "capabilities"]
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        id_value = str(data["id"]).strip()
        name_value = str(data["name"]).strip()
        version_value = str(data["version"]).strip()
        entry_value = str(data["entry"]).strip()
        if not all([id_value, name_value, version_value, entry_value]):
            raise ValueError("id, name, version and entry must be non-empty")
        capabilities_raw = data.get("capabilities")
        if not isinstance(capabilities_raw, list) or not all(isinstance(item, str) for item in capabilities_raw):
            raise ValueError("capabilities must be a list of strings")
        tools_raw = data.get("tools")
        tools: Optional[List[str]]
        if tools_raw is None:
            tools = None
        elif isinstance(tools_raw, list) and all(isinstance(item, str) for item in tools_raw):
            tools = list(tools_raw)
        else:
            raise ValueError("tools must be a list of strings when provided")
        return cls(
            id=id_value,
            name=name_value,
            version=version_value,
            entry=entry_value,
            capabilities=list(capabilities_raw),
            tools=tools,
        )


@dataclass
class PluginPolicy:
    """Security policy governing which plugins can be loaded."""

    allow: Sequence[str] = field(default_factory=lambda: ["*"])
    deny: Sequence[str] = field(default_factory=list)
    require_capabilities: Sequence[str] = field(default_factory=list)

    def is_allowed(self, manifest: Manifest) -> Tuple[bool, Optional[str]]:
        plugin_id = manifest.id
        if any(item for item in self.deny if _match(item, plugin_id)):
            return False, f"plugin '{plugin_id}' is deny-listed"
        if not any(_match(item, plugin_id) for item in self.allow):
            return False, f"plugin '{plugin_id}' is not present in allow list"
        if self.require_capabilities:
            missing = [cap for cap in self.require_capabilities if cap not in manifest.capabilities]
            if missing:
                return False, f"missing required capabilities: {', '.join(missing)}"
        return True, None


@dataclass
class PluginRecord:
    """Represents the state of a plugin."""

    manifest: Optional[Manifest]
    status: PluginStatus
    reason: Optional[str] = None
    tools: Dict[str, Dict[str, object]] = field(default_factory=dict)
    source: Optional[str] = None
    load_ms: Optional[int] = None


@dataclass
class PluginLoaderConfig:
    """Configuration for the plugin loader."""

    search_dirs: Sequence[Path]
    entry_points: str = ENTRY_POINT_GROUP
    policy: PluginPolicy = field(default_factory=PluginPolicy)


class PluginManager:
    """Load and introspect available plugins."""

    def __init__(self, config: PluginLoaderConfig):
        self._config = config
        self._records: Dict[str, PluginRecord] = {}
        self._loaded = False

    def load_all(self, force: bool = False) -> Dict[str, PluginRecord]:
        """Load plugins from entry points and directories."""

        if self._loaded and not force:
            return dict(self._records)
        self._records.clear()
        discovered = list(self._discover_entry_points()) + list(self._discover_directories())
        LOGGER.debug("Discovered %d plugin candidates", len(discovered))
        for plugin_id, loader in discovered:
            try:
                loader()
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.exception("Failed to load plugin '%s'", plugin_id)
                self._records[plugin_id] = PluginRecord(
                    manifest=None,
                    status=PluginStatus.ERROR,
                    reason=str(exc),
                    source=plugin_id,
                )
        self._loaded = True
        return dict(self._records)

    def list_plugins(self) -> List[PluginRecord]:
        self.load_all()
        return list(self._records.values())

    def get_plugin(self, plugin_id: str) -> Optional[PluginRecord]:
        self.load_all()
        return self._records.get(plugin_id)

    # Discovery helpers -------------------------------------------------

    def _discover_entry_points(self) -> Iterable[Tuple[str, callable]]:  # type: ignore[override]
        group = self._config.entry_points
        for ep in importlib_metadata.entry_points().select(group=group):
            yield ep.name, lambda ep=ep: self._load_from_entry_point(ep)

    def _discover_directories(self) -> Iterable[Tuple[str, callable]]:  # type: ignore[override]
        for directory in self._config.search_dirs:
            manifest_path = directory / MANIFEST_FILENAME
            if manifest_path.exists():
                yield directory.name, lambda path=manifest_path: self._load_from_manifest(path)
            else:
                for child in directory.glob("*/" + MANIFEST_FILENAME):
                    yield child.parent.name, lambda path=child: self._load_from_manifest(path)

    # Loading implementations ------------------------------------------

    def _load_from_entry_point(self, ep: importlib_metadata.EntryPoint) -> PluginRecord:
        module_name = ep.module
        attr = ep.attr or "register"
        plugin_id = ep.name
        manifest = Manifest(
            id=plugin_id,
            name=plugin_id,
            version="0.0.0",
            entry=f"{module_name}:{attr}",
            capabilities=["read_only"],
        )
        return self._materialise_plugin(manifest, source=f"entry_point:{plugin_id}", callable_loader=lambda: _resolve_attr(module_name, attr))

    def _load_from_manifest(self, manifest_path: Path) -> PluginRecord:
        try:
            manifest_data = load_yaml(manifest_path.read_text(encoding="utf-8")) or {}
        except YamlError as exc:
            record = PluginRecord(
                manifest=None,
                status=PluginStatus.ERROR,
                reason=f"Manifest parse error: {exc}",
                source=str(manifest_path),
            )
            self._records[manifest_path.parent.name] = record
            return record
        try:
            manifest = Manifest.from_dict(manifest_data)
        except ValueError as exc:
            record = PluginRecord(
                manifest=None,
                status=PluginStatus.ERROR,
                reason=f"Manifest validation error: {exc}",
                source=str(manifest_path),
            )
            self._records[manifest_path.parent.name] = record
            return record
        return self._materialise_plugin(manifest, source=str(manifest_path), callable_loader=lambda: _resolve_entry(manifest.entry))

    def _materialise_plugin(
        self,
        manifest: Manifest,
        *,
        source: str,
        callable_loader,
    ) -> PluginRecord:
        allowed, reason = self._config.policy.is_allowed(manifest)
        plugin_id = manifest.id
        if not allowed:
            record = PluginRecord(
                manifest=manifest,
                status=PluginStatus.BLOCKED,
                reason=reason,
                source=source,
            )
            self._records[plugin_id] = record
            return record
        start = time.perf_counter()
        try:
            register = callable_loader()
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Failed to import plugin '%s' from %s", plugin_id, source)
            record = PluginRecord(
                manifest=manifest,
                status=PluginStatus.ERROR,
                reason=str(exc),
                source=source,
            )
            self._records[plugin_id] = record
            return record
        api = PluginAPI(plugin_id=plugin_id)
        try:
            register(api)
        except PluginRegistrationError as exc:
            record = PluginRecord(
                manifest=manifest,
                status=PluginStatus.ERROR,
                reason=str(exc),
                source=source,
            )
            self._records[plugin_id] = record
            return record
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Plugin '%s' raised during registration", plugin_id)
            record = PluginRecord(
                manifest=manifest,
                status=PluginStatus.ERROR,
                reason=str(exc),
                source=source,
            )
            self._records[plugin_id] = record
            return record
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        record = PluginRecord(
            manifest=manifest,
            status=PluginStatus.LOADED,
            tools={name: {"description": reg.description} for name, reg in api.tools.items()},
            source=source,
            load_ms=elapsed_ms,
        )
        self._records[plugin_id] = record
        return record


def _match(pattern: str, value: str) -> bool:
    if pattern == "*":
        return True
    return pattern == value


def _resolve_entry(entry: str):
    if ":" in entry:
        module_name, attr = entry.split(":", 1)
    else:
        module_name, attr = entry, "register"
    return _resolve_attr(module_name, attr)


def _resolve_attr(module_name: str, attr: str):
    module = import_module(module_name)
    target = getattr(module, attr)
    if not callable(target):
        raise RuntimeError(f"{module_name}:{attr} is not callable")
    return target


def build_loader_config() -> PluginLoaderConfig:
    """Build a loader configuration from environment variables."""

    env_dir = os.environ.get("MCPDT_PLUGINS_DIR")
    search_dirs: List[Path] = []
    if env_dir:
        search_dirs.append(Path(env_dir).expanduser())
    search_dirs.extend([
        Path.home() / ".mcpdt" / "plugins",
        Path.cwd() / "plugins",
    ])

    allow = _split_env("MCPDT_PLUGINS_ALLOW", default=["*"])
    deny = _split_env("MCPDT_PLUGINS_DENY", default=[])
    policy = PluginPolicy(allow=allow, deny=deny, require_capabilities=["read_only"])
    return PluginLoaderConfig(search_dirs=search_dirs, policy=policy)


def _split_env(name: str, *, default: Sequence[str]) -> Sequence[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]
