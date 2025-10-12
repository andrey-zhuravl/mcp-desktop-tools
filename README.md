# MCP Desktop Tools

MCP Desktop Tools provides a minimal Model Context Protocol (MCP) server and a local CLI (`mcp-tools`) for inspecting source trees across configured workspaces using ripgrep and git.

## Features (A2)

- Minimal MCP server that registers the `search_text`, `git_graph`, and `repo_map` tools and handles JSON-line requests via stdin/stdout.
- Lightweight CLI (`mcp-tools`) implemented with the Python standard library.
- Workspace configuration via `workspaces.yaml` with environment overrides.
- Security helpers to keep searches inside declared workspace roots.
- Ripgrep and git adapters that enforce limits and parse structured output.
- Tool responses include elapsed timings (`elapsed_ms`, `git_cmd_ms`, `fs_walk_count`) and human-readable warnings when truncation occurs.
- Logging with configurable level through the `MCPDT_LOG` environment variable or CLI flag.

## Installation

The Python package has no third-party runtime dependencies, but external binaries are required:

- [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`) for `search_text`.
- [`git`](https://git-scm.com/) for `git_graph`.

```bash
python -m pip install -e .
```

Ensure that `rg` and `git` are available on `PATH`, or set `MCPDT_RG_PATH`/`MCPDT_GIT_PATH` to point to the binaries.

## Configuration

Workspaces are defined in `workspaces.yaml`. See [CONFIG.md](CONFIG.md) for schema details. Environment variables can override the configuration path and ripgrep binary.

## CLI Usage

Search text with ripgrep:

```bash
mcp-tools --workspace demo search_text --query "main" --include "**/*.py" --before 1 --after 1 --json
```

Summarise a git repository:

```bash
mcp-tools --workspace demo git_graph --rel-path proj --last-commits 20 --with-files --json
```

Generate a repository map:

```bash
mcp-tools --workspace demo repo_map --rel-path proj --max-depth 5 --top-dirs 30 --yaml
```

Use `--yaml` to emit YAML instead of tabular output. Commands exit with a non-zero status when the underlying tool reports an error.

## Server Usage

Start the server with:

```bash
python -m mcp_desktop_tools.server
```

The server accepts JSON lines on stdin with the following structure:

```json
{"tool": "search_text", "input": {"workspace_id": "demo", "query": "main"}}
```

Responses follow the unified schemas documented in `mcp_desktop_tools/schemas/*.json`.

## Logging

Set `MCPDT_LOG` (or `--log-level` for the CLI) to control verbosity. Logs include timing information recorded by the adapters and tool execution paths. Metrics such as `elapsed_ms`, `git_cmd_ms`, and trimming warnings are propagated in tool responses.

## Testing

Run the test suite with:

```bash
pytest -q
```

Integration tests expect both `rg` and `git` to be available.
See [SECURITY.md](SECURITY.md) and [CONFIG.md](CONFIG.md) for details about workspace security and configuration limits. Tool-specific schemas are documented in [DOCS/TOOLS.md](DOCS/TOOLS.md).
