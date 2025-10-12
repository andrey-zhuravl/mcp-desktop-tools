from pathlib import Path

import shutil

import pytest

from mcp_desktop_tools.adapters import rg


@pytest.fixture(autouse=True)
def mock_rg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/rg")


def test_build_args_fixed_strings() -> None:
    request = rg.RipgrepRequest(pattern="hello", root=Path("/tmp"), regex=True)
    args = rg.build_args(request)
    assert "--fixed-strings" in args


def test_build_args_regex() -> None:
    request = rg.RipgrepRequest(pattern="hello.*", root=Path("/tmp"), regex=True)
    args = rg.build_args(request)
    assert "--fixed-strings" not in args


def test_build_args_include_exclude() -> None:
    request = rg.RipgrepRequest(
        pattern="hello",
        root=Path("/tmp"),
        include_globs=["**/*.py"],
        exclude_globs=["**/.git/**"],
        case_sensitive=True,
        max_matches=10,
        before=1,
        after=1,
    )
    args = rg.build_args(request)
    assert "--case-sensitive" in args
    assert "--max-count" in args
    assert "--glob" in args
    assert "!**/.git/**" in args
