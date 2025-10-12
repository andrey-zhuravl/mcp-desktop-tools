from pathlib import Path

import pytest

from mcp_desktop_tools.security import path_in_workspace


def test_path_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "file.txt"
    target.write_text("demo")
    assert path_in_workspace(workspace, target) is True


def test_path_with_parent_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("demo")
    candidate = Path("../outside.txt")
    assert path_in_workspace(workspace, candidate) is False


def test_symlink_outside(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "file.txt"
    target.write_text("demo")
    symlink = workspace / "link"
    symlink.symlink_to(outside, target_is_directory=True)
    candidate = symlink / "file.txt"
    assert path_in_workspace(workspace, candidate) is False
