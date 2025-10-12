"""Definitions of the public plugin API surface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


class PluginRegistrationError(RuntimeError):
    """Raised when a plugin attempts an invalid registration."""


@dataclass
class ToolRegistration:
    """Represents a tool declared by a plugin."""

    name: str
    handler: Callable[..., object]
    description: Optional[str] = None


@dataclass
class PluginAPI:
    """Surface exposed to plugins during registration."""

    plugin_id: str
    _registered: Dict[str, ToolRegistration] = field(default_factory=dict)

    def register_tool(
        self,
        name: str,
        handler: Callable[..., object],
        *,
        description: Optional[str] = None,
    ) -> None:
        """Register a tool handler provided by the plugin."""

        if not name:
            raise PluginRegistrationError("Tool name must be a non-empty string")
        if name in self._registered:
            raise PluginRegistrationError(f"Tool '{name}' already registered for plugin {self.plugin_id}")
        if not callable(handler):
            raise PluginRegistrationError(f"Handler for '{name}' must be callable")
        self._registered[name] = ToolRegistration(name=name, handler=handler, description=description)

    def to_dict(self) -> Dict[str, object]:
        """Return a serialisable view of the registered tools."""

        return {
            name: {
                "description": reg.description,
            }
            for name, reg in self._registered.items()
        }

    @property
    def tools(self) -> Dict[str, ToolRegistration]:
        """Return a mapping of registered tool definitions."""

        return dict(self._registered)
