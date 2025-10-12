# Watchers

The watcher engine coordinates filesystem monitoring for MCP Desktop Tools. The
current implementation provides a lightweight in-process state tracker that can
be toggled via environment variables and queried through the CLI or MCP
introspection tools.

## Configuration

Environment variables influence the engine:

* ``MCPDT_WATCHERS_ENABLED`` – enable watchers when set to ``1``.
* ``MCPDT_WATCHERS_BACKEND`` – override backend auto-detection.
* ``MCPDT_WATCHERS_DEBOUNCE_MS`` – debounce period in milliseconds.
* ``MCPDT_WATCHERS_MAX_BATCH`` – cap on the number of events processed per
  batch.
* ``MCPDT_RECENT_INDEX_PATH`` – path to the open recent index file.

## Operations

* ``watchers status`` prints the current backend, queue depth and the timestamp
  of the last processed event for the selected workspace.
* ``watchers rebuild-index`` clears the pending queue for the workspace and
  marks optional relative paths as invalidated.

The engine ensures that each workspace keeps separate counters, guarding against
cross-talk between workspaces.
