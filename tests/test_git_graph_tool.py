import shutil
import subprocess
from pathlib import Path

from mcp_desktop_tools import config
from mcp_desktop_tools.tools.git_graph import GitGraphRequest, execute


def _create_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    (repo / "file.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    (repo / "file.txt").write_text("two", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "Second commit"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("feature", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "Feature commit"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    return repo


def test_git_graph(tmp_path: Path) -> None:
    if not shutil.which("git"):
        raise RuntimeError("git is required for this test")

    repo = _create_repo(tmp_path)

    workspace = config.Workspace(
        id="demo",
        path=repo,
        max_depth=None,
        excludes=[],
        tools=config.ToolPermissions(allow=["git_graph"]),
    )
    limits = config.LimitsConfig(
        max_matches=1000,
        max_output_bytes=100000,
        max_file_size_bytes=2000000,
        git_last_commits=5,
        repo_map_max_depth=5,
        repo_map_top_dirs=10,
        repo_map_follow_symlinks=False,
    )
    env = config.EnvConfig(git_path=shutil.which("git"))
    cfg = config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)

    request = GitGraphRequest(workspace_id="demo", rel_path=".", last_commits=3)
    response = execute(request, cfg)

    assert response.ok
    branch_names = {branch.name for branch in response.data.branches}
    assert {"main", "feature"}.issubset(branch_names)
    assert len(response.data.last_commits) <= 3
    assert response.data.authors
    assert Path(response.data.repo_root) == repo
