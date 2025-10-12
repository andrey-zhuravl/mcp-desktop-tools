# Changelog

# Changelog

## 0.1.0b2 – caching, concurrency, profiling

- Added disk-backed cache for `repo_map` responses with tree-signature invalidation.
- Added per-process TTL cache for `search_text` and `--no-cache` flag to disable caching.
- Implemented bounded filesystem concurrency with configurable worker counts.
- Introduced `--profile` to capture stage timings and emit structured metrics.
- Enforced subprocess timeouts for ripgrep and git adapters with configurable environment overrides.
- Added CI workflow (ruff, mypy, pytest + coverage) and developer documentation (`INSTALL.md`, `PERF.md`, `CONTRIBUTING.md`).
- Updated CLI help, README examples, and bumped package version to `0.1.0b2`.

## 0.1.0a2 – git_graph & repo_map

- Added git adapter with branch/log/shortlog parsing and exposed `git_graph` MCP tool.
- Added filesystem mapper with extension/language summaries and exposed `repo_map` MCP tool.
- Updated CLI to support `git_graph` and `repo_map` commands with JSON/YAML/tabular output.
- Extended configuration with git binary overrides and additional limit knobs.
- Documented tool schemas in `DOCS/TOOLS.md` and refreshed README usage examples.
- Bumped package version to `0.1.0a2`.
