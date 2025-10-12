"""Template registry and rendering utilities for scaffold tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional
import logging
import re

from ..utils.yaml import YamlError, load_yaml

LOGGER = logging.getLogger(__name__)


class TemplateRegistryError(RuntimeError):
    """Raised when template loading or rendering fails."""


class TemplateValidationError(TemplateRegistryError):
    """Raised when template metadata is invalid."""


@dataclass
class TemplateVariable:
    name: str
    required: bool = False
    default: Optional[str] = None
    description: Optional[str] = None


@dataclass
class TemplateFile:
    src: str
    dst: str
    executable: bool = False


@dataclass
class TemplateRenderedFile:
    path: str
    content: str
    executable: bool = False


@dataclass
class TemplateDefinition:
    template_id: str
    root: Path
    description: Optional[str] = None
    version: int = 1
    vars: Dict[str, TemplateVariable] = field(default_factory=dict)
    files: List[TemplateFile] = field(default_factory=list)

    @classmethod
    def from_path(cls, template_id: str, template_dir: Path) -> "TemplateDefinition":
        config_path = template_dir / "template.yaml"
        if not config_path.exists():
            raise TemplateValidationError(f"template.yaml not found for template '{template_id}'")
        try:
            raw = load_yaml(config_path.read_text(encoding="utf-8"))
        except (OSError, YamlError) as exc:
            raise TemplateValidationError(f"Failed to load template '{template_id}': {exc}") from exc

        name = str(raw.get("name", template_id))
        version = int(raw.get("version", 1))
        description = raw.get("description")

        vars_section = raw.get("vars", {})
        if vars_section is None:
            vars_section = {}
        if not isinstance(vars_section, Mapping):
            raise TemplateValidationError("vars section must be a mapping")
        variables: Dict[str, TemplateVariable] = {}
        for var_name, spec in vars_section.items():
            if spec is None:
                spec = {}
            if not isinstance(spec, Mapping):
                raise TemplateValidationError(f"Variable '{var_name}' specification must be a mapping")
            variables[var_name] = TemplateVariable(
                name=var_name,
                required=bool(spec.get("required", False)),
                default=str(spec.get("default")) if spec.get("default") is not None else None,
                description=str(spec.get("description")) if spec.get("description") is not None else None,
            )

        files_section = raw.get("files")
        if not isinstance(files_section, list) or not files_section:
            raise TemplateValidationError("files section must be a non-empty list")
        files: List[TemplateFile] = []
        for entry in files_section:
            if not isinstance(entry, Mapping):
                raise TemplateValidationError("Each file entry must be a mapping")
            try:
                src = str(entry["src"])
                dst = str(entry["dst"])
            except KeyError as exc:
                raise TemplateValidationError(f"Missing key in file entry: {exc.args[0]}") from exc
            executable = bool(entry.get("executable", False))
            files.append(TemplateFile(src=src, dst=dst, executable=executable))

        return cls(
            template_id=name,
            root=template_dir,
            description=str(description) if description is not None else None,
            version=version,
            vars=variables,
            files=files,
        )

    def resolve_variables(self, user_vars: Optional[Mapping[str, str]]) -> Dict[str, str]:
        resolved: Dict[str, str] = {}
        provided = {k: str(v) for k, v in (user_vars or {}).items()}
        for name, variable in self.vars.items():
            if name in provided:
                resolved[name] = provided[name]
            elif variable.default is not None:
                resolved[name] = variable.default
            elif variable.required:
                raise TemplateValidationError(f"Missing required variable '{name}' for template '{self.template_id}'")
        for key, value in provided.items():
            if key not in resolved:
                resolved[key] = value

        if "package_name" in self.vars and "package_name" not in resolved and "project_name" in resolved:
            candidate = resolved["project_name"].strip().lower()
            candidate = re.sub(r"[^a-z0-9_]+", "_", candidate)
            candidate = candidate.strip("_") or "project"
            resolved["package_name"] = candidate
        return resolved

    def render(self, variables: Optional[Mapping[str, str]], *, select: Optional[Iterable[str]] = None) -> List[TemplateRenderedFile]:
        context = self.resolve_variables(variables)

        selected: Optional[set[str]] = None
        if select is not None:
            selected = {str(Path(item).as_posix()) for item in select}

        rendered: List[TemplateRenderedFile] = []
        for entry in self.files:
            rendered_path = _render_string(entry.dst, context)

            normalized_path = str(Path(rendered_path).as_posix())
            if selected is not None and normalized_path not in selected:
                continue

            source_path = self.root / entry.src
            if not source_path.exists():
                raise TemplateRegistryError(f"Template source not found: {entry.src}")
            try:
                raw = source_path.read_text(encoding="utf-8")
            except OSError as exc:
                raise TemplateRegistryError(f"Failed to read template source '{entry.src}': {exc}") from exc

            content = _render_string(raw, context)

            rendered.append(TemplateRenderedFile(path=normalized_path, content=content, executable=entry.executable))

        return rendered


class TemplateRegistry:
    """Registry that discovers built-in and user templates."""

    def __init__(self, builtin_dir: Path, user_dirs: Optional[Iterable[Path]] = None) -> None:
        self._builtin_dir = builtin_dir
        self._user_dirs = [path for path in (user_dirs or []) if path]
        self._templates: Dict[str, TemplateDefinition] = {}
        self.refresh()

    def refresh(self) -> None:
        templates: Dict[str, TemplateDefinition] = {}
        for directory in [self._builtin_dir] + self._user_dirs:
            if not directory.exists() or not directory.is_dir():
                continue
            for child in directory.iterdir():
                if not child.is_dir():
                    continue
                try:
                    definition = TemplateDefinition.from_path(child.name, child)
                except TemplateRegistryError as exc:
                    LOGGER.warning("Skipping template in %s: %s", child, exc)
                    continue
                templates[definition.template_id] = definition
        self._templates = templates

    def list(self) -> List[str]:
        return sorted(self._templates.keys())

    def get(self, template_id: str) -> TemplateDefinition:
        if template_id not in self._templates:
            raise KeyError(f"Template '{template_id}' not found")
        return self._templates[template_id]


def load_registry(user_dir: Optional[Path] = None) -> TemplateRegistry:
    builtin_dir = Path(__file__).resolve().parent
    user_dirs: List[Path] = []
    if user_dir:
        user_dirs.append(Path(user_dir).expanduser())
    return TemplateRegistry(builtin_dir=builtin_dir, user_dirs=user_dirs)

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def _render_string(template: str, context: Mapping[str, str]) -> str:
    def _replacement(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise TemplateRegistryError(f"Missing variable '{key}' in template context")
        return context[key]

    return _PLACEHOLDER_RE.sub(_replacement, template)
