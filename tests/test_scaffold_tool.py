from pathlib import Path

from mcp_desktop_tools import config
from mcp_desktop_tools.tools.scaffold import ScaffoldRequest, execute


def _build_config(workspace_root: Path) -> config.WorkspacesConfig:
    workspace = config.Workspace(
        id="demo",
        path=workspace_root,
        tools=config.ToolPermissions(allow=["scaffold"]),
    )
    limits = config.LimitsConfig(
        scaffold_max_files=20,
        scaffold_max_total_bytes=200_000,
        recent_files_count=50,
    )
    env = config.EnvConfig()
    return config.WorkspacesConfig(version=1, workspaces=[workspace], env=env, limits=limits)


def test_scaffold_dry_run(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    request = ScaffoldRequest(
        workspace_id="demo",
        target_rel="demo_project",
        template_id="pyproject_min",
        vars={"project_name": "demo"},
        dry_run=True,
    )

    response = execute(request, cfg)
    assert response.ok
    assert response.data.stats.dry_run
    assert response.data.stats.files_written == 0
    assert not (workspace / "demo_project" / "pyproject.toml").exists()


def test_scaffold_writes_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    request = ScaffoldRequest(
        workspace_id="demo",
        target_rel="demo_project",
        template_id="pyproject_min",
        vars={"project_name": "demo", "description": "Demo"},
        dry_run=False,
    )
    response = execute(request, cfg)
    assert response.ok
    project_file = workspace / "demo_project" / "pyproject.toml"
    assert project_file.exists()
    assert "Demo" in project_file.read_text(encoding="utf-8")


def test_scaffold_overwrite_cycle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    initial = ScaffoldRequest(
        workspace_id="demo",
        target_rel="proj",
        template_id="pyproject_min",
        vars={"project_name": "proj", "description": "First"},
        dry_run=False,
    )
    second = ScaffoldRequest(
        workspace_id="demo",
        target_rel="proj",
        template_id="pyproject_min",
        vars={"project_name": "proj", "description": "Second"},
        dry_run=False,
        overwrite=True,
    )

    execute(initial, cfg)
    execute(second, cfg)

    content = (workspace / "proj" / "pyproject.toml").read_text(encoding="utf-8")
    assert "Second" in content


def test_scaffold_select_subset(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    request = ScaffoldRequest(
        workspace_id="demo",
        target_rel="proj",
        template_id="pyproject_min",
        vars={"project_name": "proj"},
        dry_run=True,
        select=["README.md"],
    )
    response = execute(request, cfg)
    assert response.ok
    planned_paths = [item.path for item in response.data.planned]
    assert planned_paths == ["proj/README.md"]


def test_scaffold_inline_security(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    request = ScaffoldRequest(
        workspace_id="demo",
        target_rel="proj",
        inline_spec={"files": [{"path": "../escape.txt", "content": "x"}]},
    )

    response = execute(request, cfg)
    assert not response.ok
    assert response.error and response.error["type"] == "path_error"


def test_scaffold_inline_absolute_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cfg = _build_config(workspace)

    request = ScaffoldRequest(
        workspace_id="demo",
        target_rel="proj",
        inline_spec={"files": [{"path": str((workspace / "absolute.txt").resolve()), "content": "x"}]},
    )

    response = execute(request, cfg)
    assert not response.ok
    assert response.error and response.error["type"] == "path_error"
