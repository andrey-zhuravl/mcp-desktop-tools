# Security Model (A1)

MCP Desktop Tools enforces a conservative security model for file system access when executing tools.

## Workspace Boundaries

- Every tool invocation must specify a workspace declared in `workspaces.yaml`.
- Paths are normalised against the workspace root. Attempts to escape the root via `..` segments or symlinks are rejected.
- Workspaces maintain allow-lists of tools; invoking a disallowed tool yields an error.

## Limits

Global limits are defined in configuration and may be overridden per request within the configured maxima:

- `max_matches`: caps the number of hits returned (enforced both during ripgrep execution and during response assembly).
- `max_output_bytes`: prevents oversized payloads by truncating results.
- `max_file_size_bytes`: skips files larger than the threshold.
- `max_depth`: the effective traversal depth is the minimum of the workspace maximum and the request value.

## External Dependencies

The only external binary used in A1 is [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`). The adapter validates that the binary exists before execution and raises a descriptive error when it is missing.

## Logging

Logs include tool invocation metadata and warnings emitted by ripgrep. The log level defaults to `INFO` and may be overridden with the `MCPDT_LOG` environment variable or the CLI `--log-level` flag.

## Plugins

The plugin loader enforces a conservative allow-list policy. By default only
plugins declaring the `read_only` capability are accepted and identifiers must
match the `MCPDT_PLUGINS_ALLOW` environment allow-list. The deny-list takes
precedence and immediately blocks the plugin before any Python code is
executed. Plugin manifests are validated against the built-in schema before the
runtime imports the plugin entry point.

## Watchers

The watcher engine keeps per-workspace event counters and honours
configuration limits such as debounce periods and maximum batch sizes. Events
outside the configured workspaces are ignored and rebuild operations reset the
queue to guard against event storms.

## Export Limits

CLI exports share a common writer that tracks the number of bytes written. When
the configured `max_output_bytes` limit is exceeded the output is truncated and
an explicit warning is emitted on stderr, preventing oversized payloads from
being delivered silently.

## Future Work

- **A2:** integrate additional repository inspection tools with the same path policy.
- **B1:** extend allow-list management to cover new tool categories and workspace presets.
- **C1:** coordinate with remote services (`*Lab`, `mlflow_homelab`) once secure transport channels are defined.
