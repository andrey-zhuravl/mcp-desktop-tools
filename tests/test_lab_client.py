import shutil
import subprocess
from pathlib import Path

import pytest

from mcp_desktop_tools import config
from mcp_desktop_tools.integrations.lab_client import LabClient


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    (repo / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, check=True)
    return repo


def _config(repo: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=repo,
        tools=config.ToolPermissions(allow=["snapshot", "git_graph", "repo_map"]),
    )
    env = config.EnvConfig(git_path=shutil.which("git"))
    limits = config.LimitsConfig(
        max_output_bytes=100000,
        git_last_commits=5,
        repo_map_max_depth=5,
        repo_map_top_dirs=5,
    )
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)


@pytest.mark.skipif(not shutil.which("git"), reason="git is required for lab client tests")
def test_lab_client_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path)
    cfg = _config(repo)
    client = LabClient(workspace_id="demo", config=cfg)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MCPDT_SNAPSHOT_INCLUDE_ENV", "1")

    response = client.snapshot(rel_path=".", mlflow_logging=False, artifact_path="snapshot.json")
    assert response.ok
    assert response.data.artifact is not None
    assert Path(response.data.artifact).exists()


@pytest.mark.skipif(not shutil.which("git"), reason="git is required for lab client tests")
def test_lab_client_snapshot_path_error(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cfg = _config(repo)
    client = LabClient(workspace_id="demo", config=cfg)

    response = client.snapshot(rel_path="../outside", mlflow_logging=False)
    assert not response.ok
    assert response.error is not None
    assert response.error["type"] == "path_error"
