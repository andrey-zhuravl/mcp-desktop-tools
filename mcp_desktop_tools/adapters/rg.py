"""Ripgrep adapter."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
import json
import logging
import re
import shlex
import shutil
import subprocess
import time

LOGGER = logging.getLogger(__name__)


class RipgrepNotFoundError(RuntimeError):
    """Raised when ripgrep binary is missing."""


@dataclass
class RipgrepRequest:
    pattern: str
    root: Path
    rg_path: str = "rg"
    regex: bool = True
    case_sensitive: bool = False
    include_globs: Optional[Iterable[str]] = None
    exclude_globs: Optional[Iterable[str]] = None
    max_matches: Optional[int] = None
    before: int = 0
    after: int = 0
    max_depth: Optional[int] = None
    max_file_size_bytes: Optional[int] = None


@dataclass
class RipgrepHit:
    file: Path
    line: int
    text: str


@dataclass
class RipgrepResult:
    hits: List[RipgrepHit]
    total: int
    elapsed_ms: int
    warnings: List[str]


def _should_use_fixed_strings(pattern: str, regex: bool) -> bool:
    if not regex:
        return True
    # If pattern has no regex special characters treat it as fixed
    specials = re.compile(r"[.\*+?{}()\[\]|^]")
    return not bool(specials.search(pattern))


def build_args(request: RipgrepRequest) -> List[str]:
    if not shutil.which(request.rg_path):
        raise RipgrepNotFoundError(f"ripgrep binary not found: {request.rg_path}")

    args = [request.rg_path, "--json"]

    if request.case_sensitive:
        args.append("--case-sensitive")
    else:
        args.append("--ignore-case")

    if _should_use_fixed_strings(request.pattern, request.regex):
        args.append("--fixed-strings")

    if request.max_matches is not None:
        args.extend(["--max-count", str(request.max_matches)])

    if request.before:
        args.extend(["--before", str(request.before)])
    if request.after:
        args.extend(["--after", str(request.after)])

    if request.max_depth is not None:
        args.extend(["--max-depth", str(request.max_depth)])

    if request.max_file_size_bytes is not None:
        args.extend(["--max-filesize", str(request.max_file_size_bytes)])

    for glob in request.include_globs or []:
        args.extend(["--glob", glob])

    for glob in request.exclude_globs or []:
        args.extend(["--glob", f"!{glob}"])

    args.extend([request.pattern, str(request.root)])
    return args


def run_ripgrep(request: RipgrepRequest) -> RipgrepResult:
    args = build_args(request)
    LOGGER.debug("Running ripgrep: %s", " ".join(shlex.quote(str(a)) for a in args))
    start = time.perf_counter()
    try:
        process = subprocess.run(
            args,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise RipgrepNotFoundError(str(exc)) from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    if process.returncode not in (0, 1):
        raise RuntimeError(f"ripgrep failed with exit code {process.returncode}: {process.stderr.strip()}")

    hits: List[RipgrepHit] = []
    total = 0
    warnings: List[str] = []

    for line in process.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("Failed to parse ripgrep line: %s", line)
            continue
        typ = payload.get("type")
        if typ == "match":
            data = payload["data"]
            path_text = data["path"]["text"]
            lines = data["lines"]["text"]
            line_number = data["line_number"]
            hits.append(RipgrepHit(file=Path(path_text), line=line_number, text=lines.rstrip("\n")))
            total += 1
        elif typ == "summary":
            total = payload["data"].get("stats", {}).get("matches", total)
        elif typ == "end" and payload.get("data", {}).get("stats", {}).get("matched_lines"):
            total = payload["data"]["stats"].get("matches", total)
        elif typ == "begin":
            continue
        elif typ == "context":
            continue
        else:
            if payload.get("type") == "summary" and payload["data"].get("stats", {}).get("unsearched_files"):
                warnings.append("Some files were skipped by ripgrep")

    return RipgrepResult(hits=hits, total=total, elapsed_ms=elapsed_ms, warnings=warnings)
