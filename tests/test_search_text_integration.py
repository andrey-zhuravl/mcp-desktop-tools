from pathlib import Path
import shutil

import pytest

from mcp_desktop_tools.config import ENV_CONFIG_PATH, load_workspaces
from mcp_desktop_tools.tools.search_text import SearchTextRequest, execute

RG_AVAILABLE = shutil.which("rg") is not None


@pytest.mark.skipif(not RG_AVAILABLE, reason="ripgrep is required for integration tests")
def test_search_text_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_root = tmp_path / "repo"
    workspace_root.mkdir()
    (workspace_root / "src").mkdir()
    (workspace_root / "src" / "main.py").write_text("def main():\n    return True\n", encoding="utf-8")
    (workspace_root / "src" / "helper.py").write_text("def helper():\n    return False\n", encoding="utf-8")
    (workspace_root / "docs").mkdir()
    (workspace_root / "docs" / "readme.md").write_text("# Title\n", encoding="utf-8")
    deep_dir = workspace_root / "nested" / "level1" / "level2"
    deep_dir.mkdir(parents=True)
    (deep_dir / "deep.py").write_text("def main():\n    pass\n", encoding="utf-8")

    config_file = tmp_path / "workspaces.yaml"
    config_file.write_text(
        f"""
version: 1
workspaces:
  - id: repo
    path: {workspace_root.as_posix()}
    max_depth: 2
    tools:
      allow: [search_text]
    excludes:
      - "**/.git/**"
limits:
  max_matches: 100
  max_output_bytes: 100000
  max_file_size_bytes: 100000
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_CONFIG_PATH, str(config_file))

    cfg = load_workspaces()

    request = SearchTextRequest(workspace_id="repo", query=r"def\s+main")
    response = execute(request, cfg)
    assert response.ok is True
    assert any("main.py" in hit.file for hit in response.data.hits)

    include_request = SearchTextRequest(
        workspace_id="repo",
        query="def",
        include_globs=["**/*.py"],
        exclude_globs=["**/docs/**"],
    )
    include_response = execute(include_request, cfg)
    assert include_response.ok
    assert all(hit.file.endswith(".py") for hit in include_response.data.hits)

    limit_request = SearchTextRequest(workspace_id="repo", query="def", max_matches=1)
    limit_response = execute(limit_request, cfg)
    assert limit_response.ok
    assert len(limit_response.data.hits) <= 1

    depth_request = SearchTextRequest(workspace_id="repo", query="def", max_depth=1)
    depth_response = execute(depth_request, cfg)
    assert depth_response.ok
    assert not any("deep.py" in hit.file for hit in depth_response.data.hits)
