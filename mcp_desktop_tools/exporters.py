"""Unified export writer for CLI and MCP responses."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List
import json

try:  # pragma: no cover - optional dependency
    import orjson  # type: ignore
except ImportError:  # pragma: no cover - fallback when orjson unavailable
    orjson = None
from .utils.yaml import dump_yaml


class ExportFormat(str, Enum):
    JSON = "json"
    YAML = "yaml"
    NDJSON = "ndjson"


@dataclass
class ExportResult:
    payload: str
    warnings: List[str]


def write_export(data, fmt: ExportFormat, *, max_output_bytes: int | None = None) -> ExportResult:
    if fmt == ExportFormat.JSON:
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        return _truncate(payload, max_output_bytes)
    if fmt == ExportFormat.YAML:
        payload = dump_yaml(data)
        return _truncate(payload, max_output_bytes)
    if fmt == ExportFormat.NDJSON:
        if not isinstance(data, Iterable):
            raise TypeError("ndjson export requires an iterable of items")
        return _write_ndjson(data, max_output_bytes=max_output_bytes)
    raise ValueError(f"Unsupported export format: {fmt}")


def _write_ndjson(items: Iterable, *, max_output_bytes: int | None) -> ExportResult:
    warnings: List[str] = []
    chunks: List[str] = []
    total = 0
    for item in items:
        if orjson is not None:
            packed = orjson.dumps(item).decode("utf-8")
        else:
            packed = json.dumps(item, ensure_ascii=False)
        packed_bytes = packed.encode("utf-8")
        addition = len(packed_bytes) + 1  # newline
        if max_output_bytes is not None and total + addition > max_output_bytes:
            warnings.append("Output truncated due to max_output_bytes")
            break
        chunks.append(packed)
        total += addition
    payload = "\n".join(chunks)
    return ExportResult(payload=payload, warnings=warnings)


def _truncate(text: str, limit: int | None) -> ExportResult:
    warnings: List[str] = []
    if limit is not None:
        encoded = text.encode("utf-8")
        if len(encoded) > limit:
            truncated = encoded[:limit]
            warnings.append("Output truncated due to max_output_bytes")
            try:
                text = truncated.decode("utf-8")
            except UnicodeDecodeError:
                text = truncated.decode("utf-8", errors="ignore")
    return ExportResult(payload=text, warnings=warnings)
