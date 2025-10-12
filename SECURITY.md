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

## Future Work

- **A2:** integrate additional repository inspection tools with the same path policy.
- **B1:** extend allow-list management to cover new tool categories and workspace presets.
- **C1:** coordinate with remote services (`*Lab`, `mlflow_homelab`) once secure transport channels are defined.
