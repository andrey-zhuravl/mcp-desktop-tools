import shutil
import subprocess
from pathlib import Path

import pytest

from mcp_desktop_tools import config
from mcp_desktop_tools.tools.snapshot import SnapshotRequest, execute


def _init_git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    (repo / "file.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, check=True)
    (repo / "file.txt").write_text("two", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "Second"], cwd=repo, check=True)
    return repo


def _build_config(repo: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=repo,
        tools=config.ToolPermissions(allow=["snapshot", "git_graph", "repo_map"]),
    )
    limits = config.LimitsConfig(
        max_output_bytes=100000,
        git_last_commits=5,
        repo_map_max_depth=5,
        repo_map_top_dirs=5,
    )
    env = config.EnvConfig(git_path=shutil.which("git"))
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)


@pytest.mark.skipif(not shutil.which("git"), reason="git is required for snapshot tests")
def test_snapshot_compose_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_git_repo(tmp_path)
    cfg = _build_config(repo)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MCPDT_SNAPSHOT_INCLUDE_ENV", "1")

    request = SnapshotRequest(
        workspace_id="demo",
        rel_path=".",
        largest_files=1,
        mlflow_logging=False,
        artifact_path="snapshot.json",
    )
    response = execute(request, cfg)

    assert response.ok
    snapshot = response.data.snapshot
    assert snapshot["workspace_id"] == "demo"
    assert snapshot["repo_root"].endswith("repo")
    assert "git" in snapshot
    assert snapshot["git"]["branch"]
    assert "fs" in snapshot
    assert snapshot["fs"]["summary"]["files"] >= 1
    assert "env" in snapshot
    assert response.data.artifact is not None
    assert Path(response.data.artifact).exists()
    largest = snapshot["fs"].get("largest_files", [])
    assert isinstance(largest, list)
    assert len(largest) <= 1


@pytest.mark.skipif(not shutil.which("git"), reason="git is required for snapshot tests")
def test_snapshot_toggle_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_git_repo(tmp_path)
    cfg = _build_config(repo)
    monkeypatch.chdir(tmp_path)

    request = SnapshotRequest(
        workspace_id="demo",
        rel_path=".",
        include_git=False,
        include_fs=False,
        include_env=False,
        mlflow_logging=False,
        artifact_path="snapshot.json",
    )
    response = execute(request, cfg)

    assert response.ok
    snapshot = response.data.snapshot
    assert "git" not in snapshot
    assert "fs" not in snapshot
    assert "env" not in snapshot


@pytest.mark.skipif(not shutil.which("git"), reason="git is required for snapshot tests")
def test_snapshot_mlflow_file_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mlflow")
    from mlflow.tracking import MlflowClient

    repo = _init_git_repo(tmp_path)
    cfg = _build_config(repo)
    tracking_dir = tmp_path / "mlruns"
    uri = f"file://{tracking_dir.as_posix()}"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MCPDT_SNAPSHOT_INCLUDE_ENV", "1")

    request = SnapshotRequest(
        workspace_id="demo",
        rel_path=".",
        mlflow_logging=True,
        mlflow_uri=uri,
        experiment="demo-exp",
        run_name="snapshot-test",
        tags={"stage": "C1"},
        artifact_path="repo_snapshot.json",
    )
    response = execute(request, cfg)

    assert response.ok
    assert response.data.mlflow is not None
    run_id = response.data.mlflow["run_id"]

    client = MlflowClient(tracking_uri=uri)
    run = client.get_run(run_id)
    assert run.data.tags["workspace_id"] == "demo"
    assert run.data.tags["stage"] == "C1"
    artifacts = client.list_artifacts(run_id)
    assert any(artifact.path == "repo_snapshot.json" for artifact in artifacts)
