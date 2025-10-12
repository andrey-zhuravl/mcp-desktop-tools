import os
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp_desktop_tools import config
from mcp_desktop_tools.tools.open_recent import OpenRecentRequest, execute


def _build_config(workspace_root: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=workspace_root,
        tools=config.ToolPermissions(allow=["open_recent"]),
        excludes=["**/ignored/**"],
    )
    limits = config.LimitsConfig(recent_files_count=10)
    env = config.EnvConfig()
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)


def _write_file(path: Path, content: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_open_recent_basic(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    base = time.time()
    _write_file(workspace / "a.py", "print()", base)
    _write_file(workspace / "b.md", "# doc", base + 10)
    _write_file(workspace / "ignored" / "c.txt", "hidden", base + 20)

    request = OpenRecentRequest(workspace_id="demo", count=5)
    response = execute(request, cfg)
    assert response.ok
    paths = [item.path for item in response.data.files]
    assert paths[0].endswith("b.md")
    assert "ignored" not in "".join(paths)
    assert response.data.total_scanned == 2


def test_open_recent_filters(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    base = time.time()
    _write_file(workspace / "main.py", "print()", base)
    _write_file(workspace / "notes.txt", "notes", base + 5)

    request = OpenRecentRequest(
        workspace_id="demo",
        extensions=[".py"],
    )
    response = execute(request, cfg)
    assert response.ok
    assert [item.path for item in response.data.files] == ["main.py"]


def test_open_recent_since(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    base = time.time()
    _write_file(workspace / "older.py", "print()", base)
    _write_file(workspace / "newer.py", "print('new')", base + 20)

    since = datetime.fromtimestamp(base + 10, tz=timezone.utc).isoformat()
    request = OpenRecentRequest(workspace_id="demo", since=since)
    response = execute(request, cfg)
    assert response.ok
    paths = [item.path for item in response.data.files]
    assert paths == ["newer.py"]
