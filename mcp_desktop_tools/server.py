"""Minimal MCP server implementation."""
from __future__ import annotations

from typing import Any, Dict
import json
import logging
import os
import sys

from .config import load_workspaces
from .tools.search_text import SearchTextRequest, execute

LOG_ENV = "MCPDT_LOG"
LOGGER = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def register(self, name: str, handler) -> None:
        LOGGER.debug("Registering tool: %s", name)
        self._tools[name] = handler

    def execute(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' is not registered")
        return self._tools[name](payload)


class MCPServer:
    def __init__(self) -> None:
        self.config = load_workspaces()
        self.registry = ToolRegistry()
        self.registry.register("search_text", self._run_search_text)
        LOGGER.info("Registered tools: %s", ", ".join(self.registry._tools.keys()))

    def _run_search_text(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request = SearchTextRequest.from_dict(payload)
        response = execute(request, self.config)
        return response.to_dict()

    def handle_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tool = payload.get("tool")
        if not tool:
            return {
                "ok": False,
                "error": {"type": "invalid_request", "message": "Missing tool name"},
                "data": {"hits": [], "total": 0},
                "warnings": [],
                "metrics": {},
            }
        try:
            tool_payload = payload.get("input", {})
            result = self.registry.execute(tool, tool_payload)
            return result
        except KeyError as exc:
            LOGGER.error("Unknown tool requested: %s", tool)
            return {
                "ok": False,
                "error": {"type": "unknown_tool", "message": str(exc)},
                "data": {"hits": [], "total": 0},
                "warnings": [],
                "metrics": {},
            }
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to execute tool %s", tool)
            return {
                "ok": False,
                "error": {"type": "execution_error", "message": str(exc)},
                "data": {"hits": [], "total": 0},
                "warnings": [],
                "metrics": {},
            }


def _configure_logging() -> None:
    level_name = os.environ.get(LOG_ENV, "INFO").upper()
    logging.basicConfig(level=level_name, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def serve_forever() -> None:
    _configure_logging()
    server = MCPServer()
    LOGGER.info("MCP server ready. Awaiting JSON lines on stdin.")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("Invalid JSON input: %s", line)
            continue
        response = server.handle_request(payload)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def main() -> None:
    try:
        serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Server interrupted, shutting down")


if __name__ == "__main__":
    main()
