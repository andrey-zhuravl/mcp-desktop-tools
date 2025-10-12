"""Command line interface for MCP Desktop Tools."""
from __future__ import annotations

from typing import List, Optional
import argparse
import json
import logging
import os
import sys

from .config import load_workspaces
from .tools.search_text import SearchTextRequest, execute
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
    return parser


def _print_table(response) -> None:
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.json and args.yaml:
        parser.error("--json and --yaml cannot be used together")

    _configure_logging(args.log_level)

    config = load_workspaces()

    if args.command != "search_text":
        parser.error("A command is required")

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

    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.yaml:
        print(dump_yaml(payload), end="")
    else:
        _print_table(response)

    return 0 if response.ok else 1


if __name__ == "__main__":
    sys.exit(main())
