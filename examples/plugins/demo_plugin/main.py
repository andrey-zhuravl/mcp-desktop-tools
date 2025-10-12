"""Demo plugin providing a simple echo tool."""
from __future__ import annotations

from typing import Any, Dict

from mcp_desktop_tools.plugins.api import PluginAPI


def register(api: PluginAPI) -> None:
    api.register_tool("echo", echo, description="Return the provided payload")


def echo(payload: Dict[str, Any]) -> Dict[str, Any]:
    message = payload.get("message") if isinstance(payload, dict) else payload
    return {"ok": True, "message": message}
