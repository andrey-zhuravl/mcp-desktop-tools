from pathlib import Path

import pytest

from mcp_desktop_tools import cache, config
from mcp_desktop_tools.adapters.rg import RipgrepHit, RipgrepResult
from mcp_desktop_tools.tools.search_text import SearchTextRequest, execute


def _build_config(workspace_root: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=workspace_root,
        max_depth=5,
        excludes=[],
        tools=config.ToolPermissions(allow=["search_text"]),
    )
    limits = config.LimitsConfig(max_matches=10, max_output_bytes=1000, max_file_size_bytes=1000)
    env = config.EnvConfig(rg_path="rg")
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    cache.reset_cache_state()
    monkeypatch.delenv("MCPDT_DISABLE_CACHE", raising=False)


def test_search_text_in_memory_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "file.txt").write_text("needle", encoding="utf-8")

    cfg = _build_config(workspace)

    hits = [RipgrepHit(file=workspace / "file.txt", line=1, text="needle")]
    result = RipgrepResult(hits=hits, total=1, elapsed_ms=5, warnings=[])

    call_count = {"run": 0}

    def _fake_run(request):  # noqa: ANN001
        call_count["run"] += 1
        return result

    monkeypatch.setenv("MCPDT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MCPDT_DISABLE_CACHE", "0")
    monkeypatch.setattr("mcp_desktop_tools.tools.search_text.run_ripgrep", _fake_run)

    request = SearchTextRequest(workspace_id="demo", query="needle", rel_path=".")
    response1 = execute(request, cfg)
    assert response1.ok
    assert response1.metrics.get("cache_hit") is False
    assert call_count["run"] == 1

    response2 = execute(request, cfg)
    assert response2.ok
    assert response2.metrics.get("cache_hit") is True
    assert call_count["run"] == 1

    request_no_cache = SearchTextRequest(workspace_id="demo", query="needle", rel_path=".", disable_cache=True)
    response3 = execute(request_no_cache, cfg)
    assert response3.ok
    assert response3.metrics.get("cache_hit") is False
    assert call_count["run"] == 2
