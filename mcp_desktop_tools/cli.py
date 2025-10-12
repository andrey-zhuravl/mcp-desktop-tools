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
from .tools.git_graph import GitGraphRequest, GitGraphResponse, execute as execute_git_graph
from .tools.open_recent import OpenRecentRequest, OpenRecentResponse, execute as execute_open_recent
from .tools.repo_map import RepoMapRequest, RepoMapResponse, execute as execute_repo_map
from .tools.snapshot import (
    SnapshotRequest,
    SnapshotResponse,
    DEFAULT_ARTIFACT_NAME as SNAPSHOT_DEFAULT_ARTIFACT,
    execute as execute_snapshot,
)
from .tools.scaffold import ScaffoldRequest, ScaffoldResponse, execute as execute_scaffold
from .tools.search_text import SearchTextRequest, SearchTextResponse, execute
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

    snapshot_parser = subparsers.add_parser("snapshot", help="Capture workspace snapshot")
    snapshot_parser.add_argument("--rel-path", required=True, dest="rel_path", help="Path inside workspace")
    snapshot_parser.add_argument("--no-git", dest="include_git", action="store_false", help="Skip git section")
    snapshot_parser.add_argument("--no-fs", dest="include_fs", action="store_false", help="Skip filesystem section")
    snapshot_parser.add_argument("--no-env", dest="include_env", action="store_false", help="Skip environment section")
    snapshot_parser.set_defaults(include_git=True, include_fs=True, include_env=True)
    snapshot_parser.add_argument("--largest-files", type=int, dest="largest_files", help="Limit largest file entries")
    snapshot_parser.add_argument("--mlflow-uri", dest="mlflow_uri", help="MLflow tracking URI override")
    snapshot_parser.add_argument("--experiment", dest="experiment", help="MLflow experiment name")
    snapshot_parser.add_argument("--run-name", dest="run_name", help="MLflow run name")
    snapshot_parser.add_argument("--tag", action="append", dest="tags", default=[], help="Tag key=value for MLflow runs")
    snapshot_parser.add_argument(
        "--artifact-path",
        dest="artifact_path",
        help=f"Snapshot artifact file name (default: {SNAPSHOT_DEFAULT_ARTIFACT})",
    )
    snapshot_parser.add_argument(
        "--no-mlflow", dest="mlflow_logging", action="store_false", help="Disable MLflow logging"
    )
    snapshot_parser.set_defaults(mlflow_logging=True)

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


def _print_snapshot(response: SnapshotResponse) -> None:
    if not response.ok:
        message = response.error.get("message") if response.error else "Unknown error"
        print(f"Error: {message}")
        for warning in response.warnings:
            print(f"Warning: {warning}")
        return

    snapshot = response.data.snapshot
    repo_root = snapshot.get("repo_root", "<unknown>")
    generated = snapshot.get("generated_at", "<unknown>")
    print(f"Snapshot for {repo_root}")
    print(f"Generated at: {generated}")

    git_section = snapshot.get("git")
    if isinstance(git_section, dict):
        branch = git_section.get("branch") or "<unknown>"
        head = git_section.get("head") or "<unknown>"
        print(f"Git branch: {branch}")
        print(f"Git head: {head}")

    fs_section = snapshot.get("fs")
    if isinstance(fs_section, dict):
        summary = fs_section.get("summary")
        if isinstance(summary, dict):
            files = summary.get("files")
            size = summary.get("bytes")
            print(f"Files: {files} Bytes: {size}")
        largest = fs_section.get("largest_files")
        if isinstance(largest, list) and largest:
            first = largest[0]
            if isinstance(first, dict):
                print(f"Largest file: {first.get('path')} ({first.get('bytes')} bytes)")

    env_section = snapshot.get("env")
    if isinstance(env_section, dict):
        os_name = env_section.get("os")
        arch = env_section.get("arch")
        python_version = env_section.get("python")
        print("Environment:")
        if os_name:
            print(f"  OS: {os_name}")
        if arch:
            print(f"  Arch: {arch}")
        if python_version:
            print(f"  Python: {python_version}")

    if response.data.artifact:
        print(f"Artifact: {response.data.artifact}")
    if response.data.mlflow:
        info = response.data.mlflow
        print("MLflow:")
        for key in ("tracking_uri", "experiment_id", "run_id"):
            value = info.get(key)
            if value:
                print(f"  {key}: {value}")

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


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.json and args.yaml:
        parser.error("--json and --yaml cannot be used together")

    _configure_logging(args.log_level)

    config = load_workspaces()

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
    elif args.command == "snapshot":
        tags: Dict[str, str] = {}
        for item in args.tags or []:
            if "=" not in item:
                parser.error(f"Invalid --tag entry '{item}', expected key=value")
            key, value = item.split("=", 1)
            tags[key] = value
        largest = args.largest_files if args.largest_files is not None else SnapshotRequest.__dataclass_fields__["largest_files"].default
        request = SnapshotRequest(
            workspace_id=args.workspace,
            rel_path=args.rel_path,
            include_git=args.include_git,
            include_fs=args.include_fs,
            include_env=args.include_env,
            largest_files=largest,
            mlflow_logging=args.mlflow_logging,
            mlflow_uri=args.mlflow_uri,
            experiment=args.experiment,
            run_name=args.run_name,
            tags=tags,
            artifact_path=args.artifact_path or SNAPSHOT_DEFAULT_ARTIFACT,
        )
        response = execute_snapshot(request, config)
        payload = response.to_dict()
        printer = _print_snapshot
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
    else:
        parser.error("A command is required")
        return 1

    if args.json:
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
