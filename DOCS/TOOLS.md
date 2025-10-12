# MCP Desktop Tools – Tool Reference

This document enumerates the MCP tools exported by the desktop server in release **0.1.0b1**. Each section outlines the intent, key input arguments, response shape, and operational limits.

## `search_text`

- **Intent:** Execute a text search inside an approved workspace using ripgrep.
- **Input:**
  - `workspace_id` *(string, required)* – Workspace identifier from `workspaces.yaml`.
  - `query` *(string, required)* – Pattern to search for.
  - `rel_path` *(string, optional)* – Directory within the workspace root. Defaults to the workspace root when omitted.
  - `regex` *(bool, default: true)* – Interpret `query` as a regular expression. If `false`, fixed-string search is used.
  - `case_sensitive` *(bool, default: false)* – Perform a case-sensitive search.
  - `include_globs` / `exclude_globs` *(array[string])* – Additional gitignore-style filters merged with workspace exclusions.
  - `max_matches`, `before`, `after`, `max_depth` – Limit match count, context lines, and traversal depth. Depth is clamped to the workspace `max_depth`.
- **Output:**
  - `data.hits` – Array of `{file, line, text, abs_path}` entries (may be truncated when size limits are reached).
  - `data.total` – Total matches reported by ripgrep.
  - `warnings` – Includes messages for truncated results or skipped files.
  - `metrics.elapsed_ms` – Tool execution time in milliseconds.
- **Limits:** Controlled by global configuration (`max_matches`, `max_output_bytes`, `max_file_size_bytes`). Ripgrep binary resolved via `rg_path` or `MCPDT_RG_PATH`.

## `git_graph`

- **Intent:** Summarise git repository state – branches, last commits, and author activity.
- **Input:**
  - `workspace_id` *(string, required)*
  - `rel_path` *(string, required)* – Path within workspace pointing to a git repository (file or directory inside the repo).
  - `last_commits` *(int, default: global `git_last_commits`)* – Number of commits to return. Hard-capped at 200.
  - `with_files` *(bool, default: false)* – When `true`, includes per-commit file stats (`git show --numstat`).
  - `authors_stats` *(bool, default: true)* – Toggle author histogram (from `git shortlog`).
- **Output:**
  - `data.repo_root` – Absolute path to the repository root.
  - `data.branches` – Array of branches with `name`, `is_current`, optional `ahead`/`behind`, and `commit` hash.
  - `data.last_commits` – Commits with `hash`, `author`, `email`, `date`, `message`, and optional `files` list when `with_files=true`.
  - `data.authors` – Author statistics (may be empty when `authors_stats=false`).
  - `metrics.elapsed_ms` and `metrics.git_cmd_ms` – Overall execution time and cumulative git process time.
- **Limits:** `last_commits` is clamped to the smaller of the request, `git_last_commits`, and the hard limit (200). `with_files=true` triggers a warning when combined with large commit counts. Git binary resolved via `git_path` config or `MCPDT_GIT_PATH`.

## `repo_map`

- **Intent:** Traverse a workspace subtree to report file counts, sizes, and language/extension distributions.
- **Input:**
  - `workspace_id` *(string, required)*
  - `rel_path` *(string, required)* – Directory within the workspace to map.
  - `max_depth` *(int, default: global `repo_map_max_depth`)* – Desired traversal depth (clamped to workspace `max_depth`).
  - `top_dirs` *(int, default: global `repo_map_top_dirs`)* – Number of top directories to include (truncated when exceeding configured limit).
  - `by_language` *(bool, default: true)* – Enable aggregated language counts (extension-based heuristics).
  - `follow_symlinks` *(bool, default: global `repo_map_follow_symlinks`)* – When `false`, symlinks are skipped. When `true`, symlink targets must remain inside the workspace.
  - `include_globs` / `exclude_globs` – Additional gitignore-style filters applied alongside workspace excludes.
- **Output:**
  - `data.summary` – Total `files` and `bytes` counted (ignores oversized/excluded files).
  - `data.top` – Ordered list of directories with aggregated file/byte counts.
  - `data.extensions` – Map of extension → file count.
  - `data.languages` – Map of detected language → file count (empty when `by_language=false`).
  - `data.largest_files` – Up to 50 largest files encountered, sorted descending by size.
  - `metrics` – Includes `elapsed_ms`, `fs_walk_count`, and `bytes_scanned`.
- **Limits:** Files exceeding `max_file_size_bytes` are skipped with warnings. Directory traversal stops once `max_depth`/`top_dirs` limits are reached. Exclusions combine workspace defaults and request-level globs.

## `scaffold`

- **Intent:** Generate files and directories from Jinja2 templates or inline specifications while enforcing workspace safety.
- **Input:**
  - `workspace_id` *(string, required)*
  - `target_rel` *(string, required)* – Directory relative to the workspace root where files are created.
  - `template_id` *(string)* – Identifier of a built-in or user template. Mutually exclusive with `inline_spec`.
  - `inline_spec` *(object)* – JSON structure describing `files: [{path, content, executable?}]`.
  - `vars` *(object[string]*) – Variables rendered into template paths and files.
  - `dry_run` *(bool, default: true)* – When `true`, only a plan is returned; no files are written.
  - `overwrite` *(bool, default: false)* – When `false`, existing files are skipped.
  - `select` *(array[string])* – Optional subset of template destinations to apply.
- **Output:**
  - `data.planned` – List of `{op, path}` items (`create`, `overwrite`, `skip`). Paths are relative to the workspace root.
  - `data.stats` – `files_planned`, `files_written`, `bytes_written`, `dry_run` flag.
  - `warnings` – Messages describing skipped files or safety issues.
- **Limits:** `scaffold_max_files` and `scaffold_max_total_bytes` cap the number of generated files and cumulative size.

See [DOCS/SCAFFOLD.md](SCAFFOLD.md) for template authoring details and GardenKeeper examples.

## `open_recent`

- **Intent:** Return a list of recently modified files within a workspace subtree without opening them.
- **Input:**
  - `workspace_id` *(string, required)*
  - `rel_path` *(string)* – Optional subdirectory to scan.
  - `count` *(int, default: global `recent_files_count`)* – Maximum files to return.
  - `extensions`, `include_globs`, `exclude_globs` – Filters applied alongside workspace excludes.
  - `since` *(string)* – ISO8601 timestamp; files older than this are ignored.
  - `follow_symlinks` *(bool, default: false)* – Whether to traverse directory symlinks.
- **Output:**
  - `data.files` – Array sorted by `mtime` descending with `path`, `abs_path`, `mtime`, and `bytes`.
  - `data.total_scanned` – Count of files considered after filtering.
  - `metrics.fs_walk_count` and `metrics.elapsed_ms` – Filesystem traversal statistics.
- **Limits:** Directory traversal respects workspace excludes and `count` is bounded by `recent_files_count`.

See [DOCS/OPEN_RECENT.md](OPEN_RECENT.md) for usage patterns.
