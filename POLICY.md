# MCP Desktop Tools Policy (C1)

This document codifies the minimum access policy and safe-usage practices for MCP Desktop Tools.

## Allowed tool surface

| Tool | Access level | Notes |
| --- | --- | --- |
| `search_text` | Read-only | Uses ripgrep under workspace root with workspace excludes and size limits. |
| `git_graph` | Read-only | Executes git commands limited to declared repository roots. |
| `repo_map` | Read-only | Collects filesystem metadata (file counts, sizes, extensions); no file content is read. |
| `open_recent` | Read-only | Lists recently modified files without opening them. |
| `snapshot` | Read-only | Composes `git_graph`, `repo_map`, and safe environment metadata into a structured JSON artifact. |
| `scaffold` | Write (guarded) | Requires explicit opt-in per workspace. Dry-run is the default and must be used unless the caller supplies `--no-dry-run`. |

Future extensions (watchers, plugin execution) are out of scope for C1 and remain disabled.

## Workspace boundaries

* Every request must provide a `workspace_id` defined in `workspaces.yaml`.
* Paths are normalised via `normalize_workspace_path` to prevent directory traversal or symlink escapes.
* Tool execution is denied when the workspace configuration does not explicitly allow it.

## Environment data whitelist

Snapshots only emit environment metadata when the process environment contains `MCPDT_SNAPSHOT_INCLUDE_ENV=1`. When enabled, the following fields are whitelisted:

* `os` – `platform.system()`
* `arch` – `platform.machine()`
* `python` – interpreter version (`platform.python_version()`)
* `tools` – versions of `rg`, `git`, and `mcp-desktop-tools` (queried via `--version`), when available.

No other environment variables or secret material are inspected or emitted.

## MLflow usage

* Provide the MLflow tracking URI via `--mlflow-uri` or the `MLFLOW_TRACKING_URI` environment variable. URIs may contain credentials, so configure them via CI secrets.
* Experiments default to `mcp-desktop-tools`, overridable with `--experiment` or `MLFLOW_EXPERIMENT_NAME`.
* Tags supplied through `--tag key=value` are propagated verbatim. Avoid encoding secrets in tags.
* When MLflow logging fails, the snapshot still completes but surfaces a warning.

## Dry-run requirements

`scaffold` and any future write-capable tools must default to dry-run (`dry_run=true`). Users must explicitly opt-in to write operations with `--no-dry-run` (CLI) or equivalent MCP request fields. Tool responses record planned operations before any mutation occurs.

## Data minimisation

* Filesystem collectors never read file contents—only metadata (`stat`) is captured.
* Oversized files (`max_file_size_bytes`) are skipped with a warning.
* `largest_files` lists are truncated to the configured or request-provided limit and may be removed entirely when `max_output_bytes` would otherwise be exceeded.
* Git history is limited by the configured `git_last_commits` cap (hard maximum of 200).

## Auditing and logging

* Structured metrics include timing fields (`elapsed_ms`, `git_cmd_ms`, `fs_walk_count`, `bytes_serialized`) for traceability.
* Tool warnings highlight skipped files, truncated results, MLflow issues, or missing environment consent.
* Server logs respect `MCPDT_LOG` / `--log-level` and should be collected in CI pipelines for audit trails.

## Responsible usage checklist

1. Confirm the workspace allows the intended tool before invoking it.
2. Use dry-run mode for any write-capable operation until the plan has been reviewed.
3. Set `MCPDT_SNAPSHOT_INCLUDE_ENV=1` only when environment metadata is safe to expose.
4. Store MLflow credentials outside of the repository (CI secrets, environment variables).
5. Archive generated snapshot artifacts (e.g., via Jenkins `archiveArtifacts`) to preserve auditability.
