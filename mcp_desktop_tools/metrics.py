"""Metrics helpers for MCP Desktop Tools."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, List
import time


class ProfileCollector:
    """Collects timing information for named stages."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled
        self._entries: List[Dict[str, int | str]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if not self._enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            self._entries.append({"stage": name, "ms": elapsed})

    def as_list(self) -> List[Dict[str, int | str]]:
        return list(self._entries)

    @property
    def enabled(self) -> bool:
        return self._enabled


def merge_metrics(base: Dict[str, int], updates: Dict[str, int | str]) -> Dict[str, int | str]:
    result: Dict[str, int | str] = dict(base)
    result.update(updates)
    return result


def add_profile(metrics: Dict[str, int | str], collector: ProfileCollector) -> Dict[str, int | str]:
    if collector.enabled and collector.as_list():
        metrics = dict(metrics)
        metrics["profile"] = collector.as_list()
    return metrics

