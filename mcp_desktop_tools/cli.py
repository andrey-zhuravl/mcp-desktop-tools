"""Command line interface for MCP Desktop Tools."""
from __future__ import annotations

from typing import List, Optional
import argparse
import json
import logging
import os
import sys

from .config import load_workspaces
from .tools.git_graph import GitGraphRequest, GitGraphResponse, execute as execute_git_graph
from .tools.repo_map import RepoMapRequest, RepoMapResponse, execute as execute_repo_map
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
        )
        response = execute_repo_map(request, config)
        payload = response.to_dict()
        printer = _print_repo_map
    else:
        parser.error("A command is required")
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.yaml:
        print(dump_yaml(payload), end="")
    else:
        printer(response)

    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
