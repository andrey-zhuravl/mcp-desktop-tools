from pathlib import Path

from mcp_desktop_tools import config
from mcp_desktop_tools.tools.repo_map import RepoMapRequest, execute


def _build_config(workspace_root: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=workspace_root,
        max_depth=5,
        excludes=["**/.git/**"],
        tools=config.ToolPermissions(allow=["repo_map"]),
    )
    limits = config.LimitsConfig(
        max_matches=1000,
        max_output_bytes=100000,
        max_file_size_bytes=120,
        git_last_commits=20,
        repo_map_max_depth=5,
        repo_map_top_dirs=10,
        repo_map_follow_symlinks=False,
    )
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=config.EnvConfig(), limits=limits)


def test_repo_map_basic(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "docs").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (workspace / "docs" / "readme.md").write_text("# Title\n", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("[core]", encoding="utf-8")
    (workspace / "data").mkdir()
    # Large file that should be skipped
    (workspace / "data" / "large.bin").write_bytes(b"0" * 500)

    cfg = _build_config(workspace)

    request = RepoMapRequest(workspace_id="demo", rel_path=".")
    response = execute(request, cfg)
    assert response.ok
    summary = response.data.summary
    # Only two files counted (main.py and readme.md)
    assert summary.files == 2
    assert response.data.extensions[".py"] == 1
    assert response.data.extensions[".md"] == 1
    assert "Skipped data/large.bin" in " ".join(response.warnings)


def test_repo_map_include_glob(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "file.py").write_text("print()", encoding="utf-8")
    (workspace / "src" / "notes.txt").write_text("notes", encoding="utf-8")

    cfg = _build_config(workspace)

    request = RepoMapRequest(
        workspace_id="demo",
        rel_path=".",
        include_globs=["*.py"],
    )
    response = execute(request, cfg)
    assert response.ok
    assert response.data.summary.files == 1
    assert ".py" in response.data.extensions
    assert ".txt" not in response.data.extensions
