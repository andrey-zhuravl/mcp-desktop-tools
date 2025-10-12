"""Concurrency helpers for MCP Desktop Tools."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple
import concurrent.futures
import os

DEFAULT_MAX_WORKERS = 32
MIN_WORKERS = 4
CPU_MULTIPLIER = 2


def _cpu_count() -> int:
    count = os.cpu_count() or MIN_WORKERS
    return max(MIN_WORKERS, count)


def default_max_workers() -> int:
    base = CPU_MULTIPLIER * _cpu_count()
    return min(DEFAULT_MAX_WORKERS, max(MIN_WORKERS, base))


def resolve_max_workers(override: Optional[int], env_override: Optional[int]) -> int:
    candidates: List[int] = []
    for value in (override, env_override):
        if value is None:
            continue
        if value > 0:
            candidates.append(value)
    if candidates:
        return max(1, min(DEFAULT_MAX_WORKERS, min(candidates)))
    return default_max_workers()


def batched(sequence: Iterable[Tuple[Path, Path]], batch_size: int) -> Iterator[List[Tuple[Path, Path]]]:
    batch: List[Tuple[Path, Path]] = []
    for item in sequence:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


@dataclass
class StatResult:
    path: Path
    rel_path: Path
    stat: Optional[os.stat_result]
    error: Optional[Exception]


def stat_paths(
    executor: concurrent.futures.ThreadPoolExecutor,
    entries: Sequence[Tuple[Path, Path]],
    *,
    follow_symlinks: bool,
) -> Iterator[StatResult]:
    def _stat(entry: Tuple[Path, Path]) -> StatResult:
        path, rel_path = entry
        try:
            info = path.stat(follow_symlinks=follow_symlinks)
            return StatResult(path=path, rel_path=rel_path, stat=info, error=None)
        except OSError as exc:
            return StatResult(path=path, rel_path=rel_path, stat=None, error=exc)

    futures = [executor.submit(_stat, item) for item in entries]
    for future in concurrent.futures.as_completed(futures):
        yield future.result()

