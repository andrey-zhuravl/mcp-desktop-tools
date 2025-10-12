# MCP Desktop Tools

MCP Desktop Tools provides a minimal Model Context Protocol (MCP) server and a local CLI (`mcp-tools`) for inspecting source trees across configured workspaces using ripgrep and git.

## Features (B2)

- Minimal MCP server registering `search_text`, `git_graph`, `repo_map`, `scaffold`, and `open_recent` tools, speaking JSON over stdin/stdout.
- Workspace configuration via `workspaces.yaml` with environment overrides.
- Security helpers to keep requests within declared workspace roots, including symlink escape detection.
- Persistent **disk cache** for `repo_map` and in-process **TTL cache** for `search_text`, with per-request opt-out (`--no-cache`).
- Bounded filesystem concurrency with tunable worker pool (`--max-workers` / `MCPDT_MAX_WORKERS`).
- Rich metrics: `elapsed_ms`, `git_cmd_ms`, `fs_walk_count`, `bytes_scanned`, `cache_hit`, and optional stage profiles (`--profile`).
- Ripgrep and git adapters with configurable timeouts (`MCPDT_SUBPROC_TIMEOUT_MS`) and warnings for truncated results.
- Logging with configurable level through `MCPDT_LOG` or the CLI `--log-level` flag.
- Scaffold and open_recent tools for generating project skeletons and listing recently modified files, with user template overrides (`MCPDT_TEMPLATES_USER_DIR`).

## Installation

See [INSTALL.md](INSTALL.md) for detailed instructions. In short:

```bash
pipx install .  # or python -m pip install -e .[dev]
```

External binaries required:

- [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`) ≥ 13.0 for `search_text`.
- [`git`](https://git-scm.com/) ≥ 2.30 for `git_graph`.

Override discovery via `MCPDT_RG_PATH` / `MCPDT_GIT_PATH` if they are not on `PATH`.

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

Scaffold a project using the built-in templates:

```bash
mcp-tools --workspace demo scaffold --target-rel demo --template-id pyproject_min --var project_name=demo --dry-run --json
```

List recently updated files:

```bash
mcp-tools --workspace demo open_recent --rel-path proj --count 20 --extensions .py --json
```

Use `--yaml` to emit YAML instead of tabular output. `--profile` prints stage timings to `stderr` and includes `metrics.profile` in structured outputs.
All cache-enabled commands accept `--no-cache`; filesystem-heavy commands accept `--max-workers` to cap concurrency.

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

Detailed usage guides for the scaffold and open_recent tools, including template formats and GardenKeeper integration examples, are available in `DOCS/SCAFFOLD.md`, `DOCS/OPEN_RECENT.md`, and `DOCS/TEMPLATES.md`.

## Logging

Set `MCPDT_LOG` (or `--log-level` for the CLI) to control verbosity. Logs include timing information recorded by the adapters and tool execution paths. Metrics such as `elapsed_ms`, `git_cmd_ms`, `bytes_scanned`, `cache_hit`, and trimming warnings are propagated in tool responses.

## Testing

Run the quality suite with:

```bash
ruff check .
mypy mcp_desktop_tools
pytest -q --cov=mcp_desktop_tools
```

Integration tests expect both `rg` and `git` to be available.
See [SECURITY.md](SECURITY.md), [CONFIG.md](CONFIG.md), [PERF.md](PERF.md), and [CONTRIBUTING.md](CONTRIBUTING.md) for additional guidance. Tool-specific schemas are documented in [DOCS/TOOLS.md](DOCS/TOOLS.md).
