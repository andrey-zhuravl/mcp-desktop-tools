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
  - id: "home"
    path: "/home/andrei"
    max_depth: 4
    excludes:
      - "**/.cache/**"
    tools:
      allow:
        - "search_text"
env:
  rg_path: "rg"
limits:
  max_matches: 1000
  max_output_bytes: 5000000
  max_file_size_bytes: 2000000
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
- `limits.max_matches` (integer, default `1000`).
- `limits.max_output_bytes` (integer, default `5000000`).
- `limits.max_file_size_bytes` (integer, default `2000000`).

### Environment Overrides

- `MCPDT_WORKSPACES`: absolute path to an alternate `workspaces.yaml` file.
- `MCPDT_RG_PATH`: path to the ripgrep binary, overrides `env.rg_path`.
- `MCPDT_LOG`: logging level (e.g. `DEBUG`, `INFO`).

## Validation Errors

The loader raises `mcp_desktop_tools.config.ValidationError` on schema mismatch and includes descriptive error messages. Duplicate workspace identifiers are rejected.

## Future Extensions

Upcoming milestones will add schema definitions for additional tools and advanced limit policies. These changes will be backward-compatible within the `version: 1` format when feasible.
