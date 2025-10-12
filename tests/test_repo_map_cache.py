from pathlib import Path

import pytest

from mcp_desktop_tools import cache, config
from mcp_desktop_tools.tools.repo_map import RepoMapRequest, execute


def _build_config(workspace_root: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=workspace_root,
        max_depth=5,
        excludes=[],
        tools=config.ToolPermissions(allow=["repo_map"]),
    )
    limits = config.LimitsConfig(
        repo_map_max_depth=5,
        repo_map_top_dirs=10,
        repo_map_follow_symlinks=False,
        max_file_size_bytes=1_000_000,
    )
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=config.EnvConfig(), limits=limits)


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.reset_cache_state()
    monkeypatch.delenv("MCPDT_CACHE_DIR", raising=False)
    monkeypatch.delenv("MCPDT_DISABLE_CACHE", raising=False)


def test_repo_map_disk_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("MCPDT_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("MCPDT_DISABLE_CACHE", "0")

    cfg = _build_config(workspace)

    request = RepoMapRequest(workspace_id="demo", rel_path=".")
    response1 = execute(request, cfg)
    assert response1.ok
    assert response1.metrics.get("cache_hit") is False

    response2 = execute(request, cfg)
    assert response2.ok
    assert response2.metrics.get("cache_hit") is True
    assert response2.metrics.get("cache_key")
