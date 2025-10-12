"""Git adapter utilities."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
import logging
import shutil
import subprocess
import time

LOGGER = logging.getLogger(__name__)


class GitError(RuntimeError):
    """Generic git invocation error."""


class GitNotFoundError(GitError):
    """Raised when git binary cannot be located."""


@dataclass
class BranchInfo:
    name: str
    is_current: bool
    ahead: Optional[int] = None
    behind: Optional[int] = None
    commit: Optional[str] = None


@dataclass
class CommitFile:
    path: str
    additions: Optional[int]
    deletions: Optional[int]


@dataclass
class CommitInfo:
    hash: str
    author: str
    email: str
    date: str
    message: str
    files: Optional[List[CommitFile]] = None


@dataclass
class AuthorStat:
    name: str
    email: str
    commits: int


def _ensure_git_available(git_path: str) -> None:
    if not shutil.which(git_path):
        raise GitNotFoundError(f"git binary not found: {git_path}")


def run_git(
    repo_path: Path,
    args: Sequence[str],
    *,
    git_path: str = "git",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command inside *repo_path* returning the completed process."""

    _ensure_git_available(git_path)
    command = [git_path, *args]
    LOGGER.debug("Running git command: %s", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_path),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise GitNotFoundError(str(exc)) from exc

    if check and completed.returncode != 0:
        raise GitError(completed.stderr.strip() or "git command failed")

    return completed


def get_repo_root(path: Path, *, git_path: str = "git") -> Path:
    process = run_git(path, ["rev-parse", "--show-toplevel"], git_path=git_path)
    output = process.stdout.strip()
    if not output:
        raise GitError("Failed to determine repository root")
    return Path(output)


def parse_branches(payload: str) -> List[BranchInfo]:
    branches: List[BranchInfo] = []
    for line in payload.splitlines():
        if not line:
            continue
        parts = line.split("\0")
        if len(parts) < 5:
            LOGGER.debug("Skipping malformed branch line: %s", line)
            continue
        name, head_flag, _, tracking, commit = parts[:5]
        ahead: Optional[int] = None
        behind: Optional[int] = None
        if tracking:
            normalized = tracking.replace(",", " ")
            tokens = normalized.split()
            for idx, token in enumerate(tokens):
                if token == "ahead" and idx + 1 < len(tokens):
                    try:
                        ahead = int(tokens[idx + 1])
                    except ValueError:
                        LOGGER.debug("Failed to parse ahead token: %s", tracking)
                if token == "behind" and idx + 1 < len(tokens):
                    try:
                        behind = int(tokens[idx + 1])
                    except ValueError:
                        LOGGER.debug("Failed to parse behind token: %s", tracking)
        branches.append(
            BranchInfo(
                name=name,
                is_current=head_flag == "*",
                ahead=ahead,
                behind=behind,
                commit=commit or None,
            )
        )
    return branches


def list_branches(repo_path: Path, *, git_path: str = "git") -> List[BranchInfo]:
    format_arg = "%(refname:short)%00%(HEAD)%00%(upstream:short)%00%(upstream:trackshort)%00%(objectname)"
    args = [
        "for-each-ref",
        "--format",
        format_arg,
        "--sort=-committerdate",
        "refs/heads",
    ]
    process = run_git(repo_path, args, git_path=git_path)
    return parse_branches(process.stdout)


def parse_log(payload: str) -> List[CommitInfo]:
    commits: List[CommitInfo] = []
    for raw in payload.split("\x1e"):
        if not raw.strip():
            continue
        record = raw
        if record.startswith("\x1e"):
            record = record[1:]
        record = record.strip("\n")
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) < 5:
            LOGGER.debug("Skipping malformed commit record: %s", record)
            continue
        commit_hash, author, email, date, message = fields[:5]
        message = message.rstrip("\n")
        commits.append(
            CommitInfo(
                hash=commit_hash,
                author=author,
                email=email,
                date=date,
                message=message,
            )
        )
    return commits


def _parse_numstat(lines: Iterable[str]) -> List[CommitFile]:
    files: List[CommitFile] = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add_raw, del_raw, path = parts
        additions = None if add_raw == "-" else int(add_raw)
        deletions = None if del_raw == "-" else int(del_raw)
        files.append(CommitFile(path=path, additions=additions, deletions=deletions))
    return files


def _load_commit_files(repo_path: Path, commit_hash: str, *, git_path: str) -> List[CommitFile]:
    process = run_git(
        repo_path,
        ["show", commit_hash, "--numstat", "--format="],
        git_path=git_path,
    )
    return _parse_numstat(process.stdout.splitlines())


def get_last_commits(
    repo_path: Path,
    *,
    git_path: str = "git",
    max_count: int = 20,
    with_files: bool = False,
) -> List[CommitInfo]:
    format_arg = "%x1e%H%x1f%an%x1f%ae%x1f%ad%x1f%B"
    args = [
        "log",
        f"--max-count={max_count}",
        "--date=iso-strict",
        "--pretty=format:" + format_arg,
        "--no-show-signature",
    ]
    process = run_git(repo_path, args, git_path=git_path)
    commits = parse_log(process.stdout)
    if with_files:
        for commit in commits:
            commit.files = _load_commit_files(repo_path, commit.hash, git_path=git_path)
    return commits


def parse_shortlog(payload: str) -> List[AuthorStat]:
    stats: List[AuthorStat] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        try:
            count_str, rest = line.strip().split("\t", 1)
            commits = int(count_str)
        except ValueError:
            LOGGER.debug("Skipping malformed shortlog line: %s", line)
            continue
        if " <" in rest and rest.endswith(">"):
            name, email = rest.rsplit(" <", 1)
            email = email.rstrip(">")
        else:
            name, email = rest, ""
        stats.append(AuthorStat(name=name, email=email, commits=commits))
    return stats


def get_author_stats(repo_path: Path, *, git_path: str = "git") -> List[AuthorStat]:
    process = run_git(repo_path, ["shortlog", "-sne", "HEAD"], git_path=git_path)
    return parse_shortlog(process.stdout)


def measure_git(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return result, elapsed_ms
