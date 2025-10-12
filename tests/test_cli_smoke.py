from pathlib import Path
import shutil
import subprocess

import pytest

from mcp_desktop_tools.cli import main
from mcp_desktop_tools.config import ENV_CONFIG_PATH

RG_AVAILABLE = shutil.which("rg") is not None
GIT_AVAILABLE = shutil.which("git") is not None


@pytest.mark.skipif(not RG_AVAILABLE, reason="ripgrep is required for CLI smoke test")
def test_cli_search_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "main.txt").write_text("main\n", encoding="utf-8")

    config_file = tmp_path / "workspaces.yaml"
    config_file.write_text(
        f"""
version: 1
workspaces:
  - id: demo
    path: {workspace_root.as_posix()}
    tools:
      allow: [search_text, git_graph, repo_map]
limits:
  max_matches: 10
  max_output_bytes: 100000
  max_file_size_bytes: 100000
""",
        encoding="utf-8",
    )

    monkeypatch.setenv(ENV_CONFIG_PATH, str(config_file))

    exit_code = main([
        "--workspace",
        "demo",
        "--json",
        "search_text",
        "--query",
        "main",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\"ok\": true" in captured.out.lower()


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is required for CLI git_graph test")
def test_cli_git_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    subprocess.run(["git", "init"], cwd=workspace_root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=workspace_root, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=workspace_root, check=True)
    (workspace_root / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=workspace_root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace_root, check=True)

    config_file = tmp_path / "workspaces.yaml"
    config_file.write_text(
        f"""
version: 1
workspaces:
  - id: demo
    path: {workspace_root.as_posix()}
    tools:
      allow: [git_graph]
limits:
  git_last_commits: 5
""",
        encoding="utf-8",
    )

    monkeypatch.setenv(ENV_CONFIG_PATH, str(config_file))

    exit_code = main([
        "--workspace",
        "demo",
        "--json",
        "git_graph",
        "--rel-path",
        ".",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\"branches\"" in captured.out


@pytest.mark.skipif(not RG_AVAILABLE, reason="ripgrep is required for CLI repo_map test")
def test_cli_repo_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "file.py").write_text("print('hi')", encoding="utf-8")

    config_file = tmp_path / "workspaces.yaml"
    config_file.write_text(
        f"""
version: 1
workspaces:
  - id: demo
    path: {workspace_root.as_posix()}
    tools:
      allow: [repo_map]
limits:
  repo_map_top_dirs: 5
""",
        encoding="utf-8",
    )

    monkeypatch.setenv(ENV_CONFIG_PATH, str(config_file))

    exit_code = main([
        "--workspace",
        "demo",
        "--json",
        "repo_map",
        "--rel-path",
        ".",
    ])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\"summary\"" in captured.out
