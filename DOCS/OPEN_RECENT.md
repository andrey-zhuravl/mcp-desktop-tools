# open_recent Tool

The `open_recent` tool lists recently modified files in a workspace without touching their contents. It is available through both the MCP server and the `mcp-tools` CLI.

## CLI Usage

```bash
mcp-tools --workspace ai-projects open_recent \
  --rel-path notebooks \
  --count 30 \
  --extensions .py --extensions .ipynb \
  --since 2025-10-01T00:00:00Z \
  --json
```

Arguments:

- `--rel-path` narrows the walk to a subdirectory.
- `--count` limits the returned file list. When omitted the global `recent_files_count` limit applies.
- `--extensions` filters by suffix. Combine with `--include`/`--exclude` globs for finer control.
- `--since` drops files older than the supplied ISO8601 timestamp.
- `--follow-symlinks` controls whether directory symlinks are traversed.

## MCP Usage

Example payload:

```json
{
  "workspace_id": "ai-projects",
  "rel_path": "GardenKeeper",
  "count": 25,
  "extensions": [".md", ".py"],
  "exclude_globs": ["**/.archive/**"],
  "since": "2025-09-15T00:00:00Z"
}
```

The response includes:

- `files`: array sorted by `mtime` descending, each entry containing `path`, `abs_path`, `mtime`, and `bytes`.
- `total_scanned`: number of filesystem entries considered after applying workspace excludes.
- `metrics.fs_walk_count`: count of directories walked.

## Workspace Safety

- All candidate paths are validated to remain under the configured workspace root.
- Workspace `excludes` from `workspaces.yaml` are merged with request-level `--exclude` patterns. Use glob syntax compatible with `.gitignore`.
- The tool never reads file contents; it only inspects metadata such as modification time and size.

## GardenKeeper Example

Combine `open_recent` with `repo_map` to build daily summaries:

```bash
mcp-tools --workspace garden open_recent --rel-path GardenKeeper --count 40 --extensions .md --json > recent.json
mcp-tools --workspace garden repo_map --rel-path GardenKeeper --json > tree.json
```

GardenKeeper can ingest `recent.json` to highlight files that changed since the last report.
