"""Configuration management for MCP Desktop Tools."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional
import os
import logging

from .utils.yaml import load_yaml

LOGGER = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when configuration validation fails."""


@dataclass
class ToolPermissions:
    allow: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "ToolPermissions":
        if data is None:
            return cls()
        allow = data.get("allow", [])
        if not isinstance(allow, list):
            raise ValidationError("tools.allow must be a list")
        return cls(allow=[str(item) for item in allow])

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allow


@dataclass
class Workspace:
    id: str
    path: Path
    max_depth: Optional[int] = None
    excludes: List[str] = field(default_factory=list)
    tools: ToolPermissions = field(default_factory=ToolPermissions)

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        try:
            workspace_id = str(data["id"])
            raw_path = data["path"]
        except KeyError as exc:
            raise ValidationError(f"Workspace is missing required field: {exc.args[0]}") from exc

        path = Path(str(raw_path)).expanduser()
        max_depth = data.get("max_depth")
        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 0):
            raise ValidationError("max_depth must be a non-negative integer")

        excludes_raw = data.get("excludes", [])
        if excludes_raw is None:
            excludes = []
        elif isinstance(excludes_raw, list):
            excludes = [str(item) for item in excludes_raw]
        else:
            raise ValidationError("excludes must be a list of strings")

        tools = ToolPermissions.from_dict(data.get("tools"))

        return cls(
            id=workspace_id,
            path=path,
            max_depth=max_depth,
            excludes=excludes,
            tools=tools,
        )


@dataclass
class EnvConfig:
    rg_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "EnvConfig":
        if not data:
            return cls()
        rg_path = data.get("rg_path")
        return cls(rg_path=str(rg_path) if rg_path is not None else None)


@dataclass
class LimitsConfig:
    max_matches: int = 1000
    max_output_bytes: int = 5_000_000
    max_file_size_bytes: int = 2_000_000

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "LimitsConfig":
        if not data:
            return cls()
        kwargs = {}
        for key in ("max_matches", "max_output_bytes", "max_file_size_bytes"):
            value = data.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or value < 0:
                raise ValidationError(f"{key} must be a non-negative integer")
            kwargs[key] = value
        return cls(**kwargs)

    def merge(self, **overrides: Optional[int]) -> "LimitsConfig":
        merged = {
            "max_matches": self.max_matches,
            "max_output_bytes": self.max_output_bytes,
            "max_file_size_bytes": self.max_file_size_bytes,
        }
        for key, value in overrides.items():
            if value is not None:
                merged[key] = value
        return LimitsConfig(**merged)


@dataclass
class WorkspacesConfig:
    version: int
    workspaces: List[Workspace]
    env: EnvConfig = field(default_factory=EnvConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspacesConfig":
        if not isinstance(data, dict):
            raise ValidationError("Configuration root must be a mapping")
        if "version" not in data:
            raise ValidationError("Configuration must include 'version'")
        if "workspaces" not in data:
            raise ValidationError("Configuration must include 'workspaces'")

        version = data["version"]
        if not isinstance(version, int):
            raise ValidationError("version must be an integer")

        workspaces_raw = data["workspaces"]
        if not isinstance(workspaces_raw, list):
            raise ValidationError("workspaces must be a list")
        workspaces = [Workspace.from_dict(item) for item in workspaces_raw]

        ids = [ws.id for ws in workspaces]
        duplicates = {identifier for identifier in ids if ids.count(identifier) > 1}
        if duplicates:
            raise ValidationError(f"Duplicate workspace ids found: {', '.join(sorted(duplicates))}")

        env = EnvConfig.from_dict(data.get("env"))
        limits = LimitsConfig.from_dict(data.get("limits"))
        return cls(version=version, workspaces=workspaces, env=env, limits=limits)

    def get_workspace(self, workspace_id: str) -> Workspace:
        for workspace in self.workspaces:
            if workspace.id == workspace_id:
                return workspace
        raise KeyError(f"Workspace '{workspace_id}' not found")


DEFAULT_CONFIG_NAME = "workspaces.yaml"
ENV_CONFIG_PATH = "MCPDT_WORKSPACES"
ENV_RG_PATH = "MCPDT_RG_PATH"


def _locate_config_file(explicit_path: Optional[Path] = None) -> Path:
    if explicit_path is not None:
        return Path(explicit_path)
    env_override = os.environ.get(ENV_CONFIG_PATH)
    if env_override:
        return Path(env_override)
    return Path(DEFAULT_CONFIG_NAME)


def load_workspaces(config_path: Optional[Path] = None) -> WorkspacesConfig:
    config_file = _locate_config_file(config_path)
    LOGGER.debug("Loading workspaces configuration from %s", config_file)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_file}")

    raw = load_yaml(config_file.read_text(encoding="utf-8"))
    config = WorkspacesConfig.from_dict(raw)

    rg_path_override = os.environ.get(ENV_RG_PATH)
    if rg_path_override:
        config.env.rg_path = rg_path_override

    return config


def list_workspace_ids(config: WorkspacesConfig) -> List[str]:
    return [ws.id for ws in config.workspaces]


def ensure_tool_allowed(workspace: Workspace, tool_name: str) -> None:
    if not workspace.tools.is_allowed(tool_name):
        raise PermissionError(f"Tool '{tool_name}' is not allowed for workspace '{workspace.id}'")


def iter_workspace_paths(config: WorkspacesConfig) -> Iterable[Path]:
    for workspace in config.workspaces:
        yield workspace.path
