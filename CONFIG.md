# Configuration Guide

## workspaces.yaml

`workspaces.yaml` defines available workspaces, default environment values, and execution limits.

```yaml
version: 1
workspaces:
  - id: "ai-projects"
    path: "D:/study/AI"
    max_depth: 6
    excludes:
      - "**/.git/**"
      - "**/.venv/**"
      - "**/node_modules/**"
    tools:
      allow:
        - "search_text"
        - "git_graph"
        - "repo_map"
  - id: "home"
    path: "/home/andrei"
    max_depth: 4
    excludes:
      - "**/.cache/**"
    tools:
      allow:
        - "search_text"
        - "git_graph"
        - "repo_map"
env:
  rg_path: "rg"
  git_path: "git"
limits:
  max_matches: 1000
  max_output_bytes: 5000000
  max_file_size_bytes: 2000000
  git_last_commits: 20
  repo_map_max_depth: 5
  repo_map_top_dirs: 50
  repo_map_follow_symlinks: false
```

### Schema

The loader validates the configuration using lightweight dataclass-based checks equivalent to the following schema:

- `version` (integer) — configuration version.
- `workspaces` (array) — each workspace requires:
  - `id` (string) — unique identifier.
  - `path` (string) — absolute filesystem path.
  - `max_depth` (integer, optional) — maximum traversal depth.
  - `excludes` (array of glob strings, optional) — patterns excluded from search.
  - `tools.allow` (array of strings) — list of enabled tools.
- `env.rg_path` (string, optional) — ripgrep binary override.
- `env.git_path` (string, optional) — git binary override.
- `limits.max_matches` (integer, default `1000`).
- `limits.max_output_bytes` (integer, default `5000000`).
- `limits.max_file_size_bytes` (integer, default `2000000`).
- `limits.git_last_commits` (integer, default `20`).
- `limits.repo_map_max_depth` (integer, default `5`).
- `limits.repo_map_top_dirs` (integer, default `50`).
- `limits.repo_map_follow_symlinks` (boolean, default `false`).

### Environment Overrides

- `MCPDT_WORKSPACES`: absolute path to an alternate `workspaces.yaml` file.
- `MCPDT_RG_PATH`: path to the ripgrep binary, overrides `env.rg_path`.
- `MCPDT_GIT_PATH`: path to the git binary, overrides `env.git_path`.
- `MCPDT_LOG`: logging level (e.g. `DEBUG`, `INFO`).

## Validation Errors

The loader raises `mcp_desktop_tools.config.ValidationError` on schema mismatch and includes descriptive error messages. Duplicate workspace identifiers are rejected.

## Future Extensions

Upcoming milestones will add schema definitions for additional tools and advanced limit policies. These changes will be backward-compatible within the `version: 1` format when feasible.
