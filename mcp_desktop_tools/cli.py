"""Command line interface for MCP Desktop Tools."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .config import load_workspaces
from .exporters import ExportFormat, write_export
from .tools.git_graph import GitGraphRequest, GitGraphResponse, execute as execute_git_graph
from .tools.open_recent import OpenRecentRequest, OpenRecentResponse, execute as execute_open_recent
from .tools.repo_map import RepoMapRequest, RepoMapResponse, execute as execute_repo_map
from .tools.scaffold import ScaffoldRequest, ScaffoldResponse, execute as execute_scaffold
from .tools.search_text import SearchTextRequest, SearchTextResponse, execute
from .tools.introspection import (
    PluginsListRequest,
    PluginsListResponse,
    PluginInfoRequest,
    PluginInfoResponse,
    WatchersStatusRequest,
    WatchersStatusResponse,
    WatchersReindexRequest,
    WatchersReindexResponse,
    plugins_list as execute_plugins_list,
    plugin_info as execute_plugin_info,
    watchers_status as execute_watchers_status,
    watchers_reindex as execute_watchers_reindex,
)
from .utils.yaml import dump_yaml

APP_NAME = "mcp-tools"
LOG_ENV = "MCPDT_LOG"


def _configure_logging(level: Optional[str]) -> None:
    env_level = os.environ.get(LOG_ENV)
    level_name = (level or env_level or "INFO").upper()
    logging.basicConfig(level=level_name, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument("--workspace", "-w", required=True, help="Workspace identifier")
    parser.add_argument("--json", action="store_true", help="Return output in JSON format")
    parser.add_argument("--yaml", action="store_true", help="Return output in YAML format")
    parser.add_argument("--log-level", help="Logging level")
    parser.add_argument("--profile", action="store_true", help="Collect and display profile metrics")
    parser.add_argument("--no-cache", action="store_true", help="Disable caches for this invocation")
    parser.add_argument("--max-workers", type=int, dest="max_workers", help="Limit worker threads for filesystem tasks")
    parser.add_argument(
        "--export-format",
        choices=[item.value for item in ExportFormat],
        dest="export_format",
        help="Serialise output using the selected format",
    )
    parser.add_argument(
        "--max-output-bytes",
        type=int,
        dest="max_output_bytes",
        help="Limit the number of bytes written by the export writer",
    )

    subparsers = parser.add_subparsers(dest="command")

    search_parser = subparsers.add_parser("search_text", help="Run text search")
    search_parser.add_argument("--query", "-q", required=True, help="Search query")
    search_parser.add_argument("--regex", dest="regex", action="store_true", default=True, help="Treat query as regex")
    search_parser.add_argument("--fixed", dest="regex", action="store_false", help="Treat query as fixed string")
    search_parser.add_argument("--case-sensitive", dest="case_sensitive", action="store_true", help="Case sensitive search")
    search_parser.add_argument("--ignore-case", dest="case_sensitive", action="store_false", help="Case insensitive search")
    search_parser.set_defaults(case_sensitive=False)
    search_parser.add_argument("--include", action="append", default=[], help="Glob to include")
    search_parser.add_argument("--exclude", action="append", default=[], help="Glob to exclude")
    search_parser.add_argument("--before", type=int, default=0, help="Lines of context before match")
    search_parser.add_argument("--after", type=int, default=0, help="Lines of context after match")
    search_parser.add_argument("--max-matches", type=int, dest="max_matches", help="Maximum matches to return")
    search_parser.add_argument("--max-depth", type=int, dest="max_depth", help="Maximum search depth")
    search_parser.add_argument("--rel-path", dest="rel_path", help="Path relative to workspace root")
    git_graph_parser = subparsers.add_parser("git_graph", help="Summarise git repository state")
    git_graph_parser.add_argument("--rel-path", required=True, dest="rel_path", help="Path to git repository")
    git_graph_parser.add_argument("--last-commits", type=int, dest="last_commits", help="Number of commits to return")
    git_graph_parser.add_argument("--with-files", dest="with_files", action="store_true", help="Include files per commit")
    git_graph_parser.add_argument("--no-with-files", dest="with_files", action="store_false", help="Exclude files per commit")
    git_graph_parser.set_defaults(with_files=False)
    git_graph_parser.add_argument("--no-authors-stats", dest="authors_stats", action="store_false", help="Skip author statistics")
    git_graph_parser.set_defaults(authors_stats=True)

    repo_map_parser = subparsers.add_parser("repo_map", help="Analyse repository file tree")
    repo_map_parser.add_argument("--rel-path", required=True, dest="rel_path", help="Path inside workspace")
    repo_map_parser.add_argument("--max-depth", type=int, dest="max_depth", help="Maximum depth to walk")
    repo_map_parser.add_argument("--top-dirs", type=int, dest="top_dirs", help="Number of top directories to include")
    repo_map_parser.add_argument("--by-language", dest="by_language", action="store_true", help="Include language summary")
    repo_map_parser.add_argument("--no-by-language", dest="by_language", action="store_false", help="Exclude language summary")
    repo_map_parser.set_defaults(by_language=True)
    repo_map_parser.add_argument("--follow-symlinks", dest="follow_symlinks", action="store_true", help="Follow symlinks")
    repo_map_parser.add_argument("--no-follow-symlinks", dest="follow_symlinks", action="store_false", help="Do not follow symlinks")
    repo_map_parser.set_defaults(follow_symlinks=None)
    repo_map_parser.add_argument("--include", action="append", default=[], help="Glob to include")
    repo_map_parser.add_argument("--exclude", action="append", default=[], help="Glob to exclude")

    scaffold_parser = subparsers.add_parser("scaffold", help="Generate files from templates")
    scaffold_parser.add_argument("--target-rel", required=True, dest="target_rel", help="Target directory relative to workspace")
    group = scaffold_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template-id", dest="template_id", help="Identifier of template to apply")
    group.add_argument("--inline-spec", dest="inline_spec", help="Path to inline JSON specification")
    scaffold_parser.add_argument("--var", action="append", default=[], help="Template variable in key=value form")
    scaffold_parser.add_argument("--select", action="append", default=[], help="Subset of template paths to apply")
    scaffold_parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=None, help="Preview operations without writing (default)")
    scaffold_parser.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Write files to disk")
    scaffold_parser.add_argument("--overwrite", dest="overwrite", action="store_true", help="Overwrite existing files")
    scaffold_parser.add_argument("--no-overwrite", dest="overwrite", action="store_false", help="Skip existing files (default)")
    scaffold_parser.set_defaults(overwrite=False)

    open_recent_parser = subparsers.add_parser("open_recent", help="List recently modified files")
    open_recent_parser.add_argument("--rel-path", dest="rel_path", help="Path inside workspace")
    open_recent_parser.add_argument("--count", type=int, dest="count", help="Number of files to return")
    open_recent_parser.add_argument("--extensions", action="append", default=[], help="Filter by extension (e.g. .py)")
    open_recent_parser.add_argument("--include", action="append", default=[], help="Glob to include")
    open_recent_parser.add_argument("--exclude", action="append", default=[], help="Glob to exclude")
    open_recent_parser.add_argument("--since", dest="since", help="Filter files modified after ISO8601 timestamp")
    open_recent_parser.add_argument("--follow-symlinks", dest="follow_symlinks", action="store_true", help="Follow symlinks when walking")
    open_recent_parser.add_argument("--no-follow-symlinks", dest="follow_symlinks", action="store_false", help="Do not follow symlinks (default)")
    open_recent_parser.set_defaults(follow_symlinks=False)

    plugins_parser = subparsers.add_parser("plugins", help="Plugin management commands")
    plugins_sub = plugins_parser.add_subparsers(dest="plugins_command")
    plugins_sub.required = True

    plugins_list_parser = plugins_sub.add_parser("list", help="List available plugins")
    plugins_list_parser.add_argument("--filter", dest="filter", help="Filter plugins by id or name")

    plugins_info_parser = plugins_sub.add_parser("info", help="Show plugin details")
    plugins_info_parser.add_argument("plugin_id", help="Identifier of the plugin")

    watchers_parser = subparsers.add_parser("watchers", help="Filesystem watcher commands")
    watchers_sub = watchers_parser.add_subparsers(dest="watchers_command")
    watchers_sub.required = True

    watchers_sub.add_parser("status", help="Display watcher status")

    watchers_rebuild_parser = watchers_sub.add_parser("rebuild-index", help="Rebuild watchers index")
    watchers_rebuild_parser.add_argument("--rel-path", dest="rel_path", help="Optional relative path to target")

    return parser


def _print_table(response: SearchTextResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        return
    if not response.data.hits:
        print("No results found")
        return
    widths = [0, 0, 0]
    rows: List[List[str]] = []
    for hit in response.data.hits:
        row = [hit.file, str(hit.line), hit.text]
        rows.append(row)
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    header = ["File", "Line", "Text"]
    widths = [max(widths[i], len(header[i])) for i in range(3)]
    print(" | ".join(header[i].ljust(widths[i]) for i in range(3)))
    print("-+-".join("-" * widths[i] for i in range(3)))
    for row in rows:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(3)))
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_git_graph(response: GitGraphResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        return
    print(f"Repository: {response.data.repo_root}")
    print("Branches:")
    for branch in response.data.branches:
        marker = "*" if branch.is_current else " "
        ahead = f" +{branch.ahead}" if branch.ahead is not None else ""
        behind = f" -{branch.behind}" if branch.behind is not None else ""
        print(f"  {marker} {branch.name}{ahead}{behind}")
    print("Last commits:")
    for commit in response.data.last_commits:
        print(f"  {commit.hash[:8]} {commit.author} <{commit.email}> {commit.date}")
        first_line = commit.message.splitlines()[0] if commit.message else ""
        print(f"    {first_line}")
        if commit.files:
            for file in commit.files[:5]:
                additions = file.additions if file.additions is not None else 0
                deletions = file.deletions if file.deletions is not None else 0
                print(f"      +{additions} -{deletions} {file.path}")
            if len(commit.files) > 5:
                print("      ...")
    if response.data.authors:
        print("Authors:")
        for author in response.data.authors:
            print(f"  {author.commits:>5} {author.name} <{author.email}>")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_repo_map(response: RepoMapResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        return
    summary = response.data.summary
    print(f"Files: {summary.files}")
    print(f"Bytes: {summary.bytes}")
    if response.data.top:
        print("Top directories:")
        for item in response.data.top:
            print(f"  {item.dir}: {item.files} files, {item.bytes} bytes")
    if response.data.extensions:
        print("Extensions:")
        for ext, count in sorted(response.data.extensions.items(), key=lambda kv: kv[1], reverse=True):
            label = ext or "<none>"
            print(f"  {label}: {count}")
    if response.data.languages:
        print("Languages:")
        for lang, count in sorted(response.data.languages.items(), key=lambda kv: kv[1], reverse=True):
            print(f"  {lang}: {count}")
    if response.data.largest_files:
        print("Largest files:")
        for item in response.data.largest_files[:10]:
            print(f"  {item['path']}: {item['bytes']} bytes")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_scaffold(response: ScaffoldResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        for warning in response.warnings:
            print(f"Warning: {warning}")
        return
    if not response.data.planned:
        print("No operations planned")
    else:
        print("Planned operations:")
        for op in response.data.planned:
            print(f"  {op.op.upper():<10} {op.path}")
    stats = response.data.stats
    print("Stats:")
    print(f"  files_planned: {stats.files_planned}")
    print(f"  files_written: {stats.files_written}")
    print(f"  bytes_written: {stats.bytes_written}")
    print(f"  dry_run: {stats.dry_run}")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_open_recent(response: OpenRecentResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        for warning in response.warnings:
            print(f"Warning: {warning}")
        return
    if not response.data.files:
        print("No files matched filters")
    else:
        print("Recent files:")
        for item in response.data.files:
            print(f"  {item.mtime} {item.path} ({item.bytes} bytes)")
    print(f"Total scanned: {response.data.total_scanned}")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_profile_metrics(metrics: Dict[str, object]) -> None:
    profile_data = metrics.get("profile") if isinstance(metrics, dict) else None
    if not isinstance(profile_data, list) or not profile_data:
        return
    rows: List[Tuple[str, str]] = []
    stage_width = len("Stage")
    duration_width = len("ms")
    for item in profile_data:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage", ""))
        duration = str(item.get("ms", ""))
        rows.append((stage, duration))
        stage_width = max(stage_width, len(stage))
        duration_width = max(duration_width, len(duration))
    if not rows:
        return
    print("Profile:", file=sys.stderr)
    header = f"{'Stage'.ljust(stage_width)} | {'ms'.rjust(duration_width)}"
    print(header, file=sys.stderr)
    print(f"{'-' * stage_width}-+-{'-' * duration_width}", file=sys.stderr)
    for stage, duration in rows:
        print(f"{stage.ljust(stage_width)} | {duration.rjust(duration_width)}", file=sys.stderr)


def _print_plugins_list(response: PluginsListResponse) -> None:
    plugins = response.data.get("plugins") if isinstance(response.data, dict) else None
    if not plugins:
        print("No plugins discovered")
        return
    for item in plugins:
        print(f"{item['id']} ({item['status']}) - {item['name']} {item['version']}")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_plugin_info(response: PluginInfoResponse) -> None:
    if not response.ok:
        print("Error: unable to retrieve plugin information")
        for warning in response.warnings:
            print(f"Warning: {warning}")
        return
    manifest = response.data.get("manifest") if isinstance(response.data, dict) else None
    if manifest:
        print(f"ID: {manifest.get('id')}")
        print(f"Name: {manifest.get('name')}")
        print(f"Version: {manifest.get('version')}")
        print(f"Entry: {manifest.get('entry')}")
        print(f"Capabilities: {', '.join(manifest.get('capabilities', []))}")
    print(f"Status: {response.data.get('status')}")
    reason = response.data.get('reason')
    if reason:
        print(f"Reason: {reason}")
    tools = response.data.get("tools", [])
    if tools:
        print("Tools:")
        for tool in tools:
            print(f"  - {tool}")
    for warning in response.warnings:
        print(f"Warning: {warning}")


def _print_watchers_status(response: WatchersStatusResponse) -> None:
    if not response.ok:
        print("Error: unable to retrieve watcher status")
        return
    data = response.data
    print(f"Enabled: {data.get('enabled')}")
    print(f"Backend: {data.get('backend')}")
    print(f"Watchers: {data.get('watchers_count')}")
    print(f"Queued events: {data.get('queued_events')}")
    if data.get("last_event_ts"):
        print(f"Last event: {data.get('last_event_ts')}")


def _print_watchers_reindex(response: WatchersReindexResponse) -> None:
    data = response.data
    print(f"Reindexed: {data.get('reindexed')}")
    invalidated = data.get("invalidated") or []
    if invalidated:
        print("Invalidated paths:")
        for item in invalidated:
            print(f"  - {item}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.json and args.yaml:
        parser.error("--json and --yaml cannot be used together")
    if args.export_format and (args.json or args.yaml):
        parser.error("--export-format cannot be combined with --json/--yaml")

    _configure_logging(args.log_level)

    config = load_workspaces()

    export_items: Optional[List[Dict[str, object]]] = None

    if args.command == "search_text":
        request = SearchTextRequest(
            workspace_id=args.workspace,
            query=args.query,
            rel_path=args.rel_path,
            regex=args.regex,
            case_sensitive=args.case_sensitive,
            include_globs=args.include or [],
            exclude_globs=args.exclude or [],
            max_matches=args.max_matches,
            before=args.before,
            after=args.after,
            max_depth=args.max_depth,
            disable_cache=args.no_cache,
            profile=args.profile,
        )
        response = execute(request, config)
        payload = response.to_dict()
        printer = _print_table
    elif args.command == "git_graph":
        request = GitGraphRequest(
            workspace_id=args.workspace,
            rel_path=args.rel_path,
            last_commits=args.last_commits,
            with_files=args.with_files,
            authors_stats=args.authors_stats,
        )
        response = execute_git_graph(request, config)
        payload = response.to_dict()
        printer = _print_git_graph
    elif args.command == "repo_map":
        request = RepoMapRequest(
            workspace_id=args.workspace,
            rel_path=args.rel_path,
            max_depth=args.max_depth,
            top_dirs=args.top_dirs,
            by_language=args.by_language,
            follow_symlinks=args.follow_symlinks,
            include_globs=args.include or [],
            exclude_globs=args.exclude or [],
            disable_cache=args.no_cache,
            profile=args.profile,
            max_workers=args.max_workers,
        )
        response = execute_repo_map(request, config)
        payload = response.to_dict()
        printer = _print_repo_map
    elif args.command == "scaffold":
        vars_map = {}
        for item in args.var or []:
            if "=" not in item:
                parser.error(f"Invalid --var entry '{item}', expected key=value")
            key, value = item.split("=", 1)
            vars_map[key] = value
        inline_payload = None
        if args.inline_spec:
            inline_path = Path(args.inline_spec)
            if not inline_path.exists():
                parser.error(f"Inline specification file not found: {inline_path}")
            try:
                inline_payload = json.loads(inline_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                parser.error(f"Invalid inline specification JSON: {exc}")
        dry_run = args.dry_run
        if dry_run is None:
            default = config.env.scaffold_default_dry_run
            dry_run = True if default is None else bool(default)
        request = ScaffoldRequest(
            workspace_id=args.workspace,
            target_rel=args.target_rel,
            template_id=args.template_id,
            inline_spec=inline_payload,
            vars=vars_map,
            dry_run=dry_run,
            overwrite=args.overwrite,
            select=args.select or [],
        )
        response = execute_scaffold(request, config)
        payload = response.to_dict()
        printer = _print_scaffold
    elif args.command == "open_recent":
        request = OpenRecentRequest(
            workspace_id=args.workspace,
            rel_path=args.rel_path,
            count=args.count,
            extensions=args.extensions or [],
            include_globs=args.include or [],
            exclude_globs=args.exclude or [],
            since=args.since,
            follow_symlinks=args.follow_symlinks,
        )
        response = execute_open_recent(request, config)
        payload = response.to_dict()
        printer = _print_open_recent
    elif args.command == "plugins":
        if args.plugins_command == "list":
            request = PluginsListRequest(filter=args.filter)
            response = execute_plugins_list(request)
            payload = response.to_dict()
            printer = _print_plugins_list
            data_plugins = response.data.get("plugins") if isinstance(response.data, dict) else None
            if isinstance(data_plugins, list):
                export_items = data_plugins
        elif args.plugins_command == "info":
            request = PluginInfoRequest(plugin_id=args.plugin_id)
            response = execute_plugin_info(request)
            payload = response.to_dict()
            printer = _print_plugin_info
        else:
            parser.error("plugins command requires a sub-command")
            return 1
    elif args.command == "watchers":
        workspace_id = args.workspace
        if not workspace_id:
            parser.error("--workspace is required")
            return 1
        if args.watchers_command == "status":
            request = WatchersStatusRequest(workspace_id=workspace_id)
            response = execute_watchers_status(request)
            payload = response.to_dict()
            printer = _print_watchers_status
        elif args.watchers_command == "rebuild-index":
            request = WatchersReindexRequest(workspace_id=workspace_id, rel_path=args.rel_path)
            response = execute_watchers_reindex(request)
            payload = response.to_dict()
            printer = _print_watchers_reindex
        else:
            parser.error("watchers command requires a sub-command")
            return 1
    else:
        parser.error("A command is required")
        return 1

    if args.export_format:
        fmt = ExportFormat(args.export_format)
        target = payload
        if fmt is ExportFormat.NDJSON:
            if export_items is None:
                parser.error("Command does not support ndjson export")
                return 1
            target = export_items
        result = write_export(target, fmt, max_output_bytes=args.max_output_bytes)
        print(result.payload)
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
    elif args.json:
        print(json.dumps(payload, indent=2))
    elif args.yaml:
        print(dump_yaml(payload), end="")
    else:
        printer(response)

    if args.profile:
        _print_profile_metrics(response.metrics)

    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
