"""Plugin subsystem for MCP Desktop Tools."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from .loader import PluginManager, PluginLoaderConfig, build_loader_config


@lru_cache(maxsize=1)
def get_plugin_manager(config: Optional[PluginLoaderConfig] = None) -> PluginManager:
    """Return a process-wide plugin manager instance.

    Parameters
    ----------
    config:
        Optional pre-built configuration. If omitted a configuration is built
        from the current environment using :func:`build_loader_config`.
    """

    loader_config = config or build_loader_config()
    return PluginManager(loader_config)


__all__ = [
    "PluginManager",
    "PluginLoaderConfig",
    "build_loader_config",
    "get_plugin_manager",
]
