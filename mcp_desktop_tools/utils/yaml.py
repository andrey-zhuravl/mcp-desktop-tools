"""Minimal YAML utilities with limited feature support."""
from __future__ import annotations

from typing import Any, Iterable, List, Tuple


class YamlError(ValueError):
    """Raised when YAML parsing fails."""


def _split_lines(text: str) -> List[Tuple[int, str]]:
    lines: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.split("#", 1)[0].rstrip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise YamlError("Indentation must be multiples of 2 spaces")
        lines.append((indent, stripped.lstrip()))
    return lines


def _parse_scalar(value: str) -> Any:
    if value == '' or value == 'null' or value == '~':
        return None
    lower = value.lower()
    if lower == 'true':
        return True
    if lower == 'false':
        return False
    if value.startswith('[') and value.endswith(']'):
        inner = value[1:-1].strip()
        if not inner:
            return []
        parts = [part.strip() for part in inner.split(',') if part.strip()]
        result = []
        for part in parts:
            if (part.startswith('"') and part.endswith('"')) or (part.startswith("'") and part.endswith("'")):
                result.append(part[1:-1])
            else:
                result.append(part)
        return result
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

def _parse_block(lines: List[Tuple[int, str]], start: int, indent: int) -> Tuple[Any, int]:
    container = None
    i = start
    while i < len(lines):
        line_indent, content = lines[i]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise YamlError("Invalid indentation level")

        if content.startswith("- "):
            if container is None:
                container = []
            elif not isinstance(container, list):
                raise YamlError("List item encountered in mapping context")
            item = content[2:].strip()
            if not item:
                value, i = _parse_block(lines, i + 1, indent + 2)
                container.append(value)
                continue
            if ':' in item:
                key, value_part = item.split(':', 1)
                key = key.strip()
                value_part = value_part.strip()
                entry = {}
                if value_part:
                    entry[key] = _parse_scalar(value_part)
                    i += 1
                    if i < len(lines) and lines[i][0] > indent:
                        nested, i = _parse_block(lines, i, indent + 2)
                        if isinstance(nested, dict):
                            entry.update(nested)
                        else:
                            entry['value'] = nested
                else:
                    entry[key], i = _parse_block(lines, i + 1, indent + 2)
                container.append(entry)
                continue
            container.append(_parse_scalar(item))
            i += 1
        else:
            if container is None:
                container = {}
            elif isinstance(container, list):
                raise YamlError("Mapping entry encountered in list context")
            if ":" not in content:
                raise YamlError(f"Invalid mapping entry: {content}")
            key, value_part = content.split(":", 1)
            key = key.strip()
            value_part = value_part.strip()
            if value_part:
                container[key] = _parse_scalar(value_part)
                i += 1
                continue
            value, i = _parse_block(lines, i + 1, indent + 2)
            container[key] = value
        # continue loop if we already incremented
        if isinstance(container, list):
            continue
    if container is None:
        return {}, i
    return container, i


def load_yaml(text: str) -> Any:
    lines = _split_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise YamlError("Failed to consume entire document")
    return value


def _dump_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(ch in text for ch in [":", "#", "\n", "\""]):
        return f'"{text}"'
    return text


def _dump_block(value: Any, indent: int) -> List[str]:
    prefix = " " * indent
    lines: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_dump_block(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_dump_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_dump_block(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_dump_scalar(item)}")
    else:
        lines.append(f"{prefix}{_dump_scalar(value)}")
    return lines


def dump_yaml(data: Any) -> str:
    return "\n".join(_dump_block(data, 0)) + "\n"
