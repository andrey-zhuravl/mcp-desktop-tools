# Performance and Profiling

MCP Desktop Tools B2 introduces persistent caching and bounded concurrency to accelerate repeated filesystem traversals and text
 searches.

## Disk cache for `repo_map`

* Cached under `~/.mcpdt/cache` (override with `MCPDT_CACHE_DIR`).
* Keys include workspace id, traversal parameters, include/exclude globs, and a tree signature derived from directory metadata.
* Entries expire after **1 hour** by default (`MCPDT_CACHE_TTL_SEC`).
* Disable globally via `MCPDT_DISABLE_CACHE=1` or per-invocation with `mcp-tools --no-cache`.
* Metrics include `cache_hit`, `cache_key`, `fs_walk_count`, `bytes_scanned`, and `max_workers`.

## In-memory cache for `search_text`

* TTL cache scoped to the running process with a 120 second expiry.
* Cache key factors in workspace, query, glob filters, depth, and regex flags.
* Disable with `--no-cache` / `MCPDT_DISABLE_CACHE=1`.
* Metrics include `cache_hit`, `rg_elapsed_ms`, and `cache_key`.

## Concurrency controls

* Filesystem traversal uses a bounded thread pool with the default size `min(32, max(4, 2*CPU))`.
* Override with `mcp-tools --max-workers <N>` or `MCPDT_MAX_WORKERS`.
* The traversal batches file stat operations (`fs_batch_size=256`) to balance throughput with memory usage.

## Subprocess timeouts

* ripgrep and git invocations default to **30s** (`MCPDT_SUBPROC_TIMEOUT_MS`).
* Timeouts raise `TimeoutError` surfaced in CLI warnings/metrics.

## Profiling

* Use `mcp-tools --profile ...` to capture stage timings. Tables are printed to `stderr`; structured data is included in the `me
trics.profile` array.
* Stages:
  * `signature`, `cache_lookup`, `walk` for `repo_map`.
  * `build_args`, `run_rg`, `parse` for `search_text`.
  * git operations contribute to `git_cmd_ms` in metrics.

## Recommendations

* Warm caches on large repositories to benefit from disk reuse.
* Tune `--max-workers` downward on slow disks or networked filesystems to reduce contention.
* Combine `--include/--exclude` globs to reduce `bytes_scanned` and pressure on caches.
* Record representative timings in this file after running benchmarks (e.g., 40%+ speed-up on cached repo_map traversals).
