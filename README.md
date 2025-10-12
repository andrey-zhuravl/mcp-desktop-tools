# MCP Desktop Tools

MCP Desktop Tools provides a minimal Model Context Protocol (MCP) server and a local CLI (`mcp-tools`) for searching text across configured workspaces using ripgrep.

## Features (A1)

- Minimal MCP server that registers the `search_text` tool and handles JSON-line requests via stdin/stdout.
- Lightweight CLI (`mcp-tools`) implemented with the Python standard library.
- Workspace configuration via `workspaces.yaml` with environment overrides.
- Security helpers to keep searches inside declared workspace roots.
- Ripgrep adapter that enforces limits and parses JSON output.
- Logging with configurable level through the `MCPDT_LOG` environment variable or CLI flag.

## Installation

The project has no third-party runtime dependencies. Optional tools such as `rg` must be installed separately.

```bash
python -m pip install -e .
```

Ensure that [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`) is installed and accessible via `PATH` or set `MCPDT_RG_PATH` to the binary location.

## Configuration

Workspaces are defined in `workspaces.yaml`. See [CONFIG.md](CONFIG.md) for schema details. Environment variables can override the configuration path and ripgrep binary.

## CLI Usage

```bash
mcp-tools --workspace demo search_text --query "main" --include "**/*.py" --before 1 --after 1 --json
```

Use `--yaml` to emit YAML instead of tabular output. The command exits with a non-zero status when the tool reports an error.

## Server Usage

Start the server with:

```bash
python -m mcp_desktop_tools.server
```

The server accepts JSON lines on stdin with the following structure:

```json
{"tool": "search_text", "input": {"workspace_id": "demo", "query": "main"}}
```

Responses follow the unified schema documented in [schemas/search_text.json](mcp_desktop_tools/schemas/search_text.json).

## Logging

Set `MCPDT_LOG` (or `--log-level` for the CLI) to control verbosity. Logs include timing information recorded by the ripgrep adapter and tool execution paths.

## Testing

Run the test suite with:

```bash
pytest -q
```

Integration tests expect `rg` to be available.

## Roadmap

See [SECURITY.md](SECURITY.md) and [CONFIG.md](CONFIG.md) for more information about future milestones (A2/B1/C1).
