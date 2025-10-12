from pathlib import Path

from pathlib import Path

import textwrap

import pytest
from mcp_desktop_tools import config
from mcp_desktop_tools.config import ValidationError


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "workspaces.yaml"
    path.write_text(textwrap.dedent(content))
    return path


def test_load_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(
        tmp_path,
        """
        version: 1
        workspaces:
          - id: demo
            path: {path}
            tools:
              allow: [search_text]
        """.format(path=tmp_path.as_posix()),
    )
    monkeypatch.setenv(config.ENV_CONFIG_PATH, str(cfg))
    loaded = config.load_workspaces()
    assert loaded.version == 1
    assert loaded.get_workspace("demo").path == Path(tmp_path)


def test_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg1 = _write_config(
        tmp_path,
        """
        version: 1
        workspaces:
          - id: a
            path: /tmp/a
            tools:
              allow: [search_text]
        """,
    )
    cfg2 = _write_config(
        tmp_path,
        """
        version: 1
        workspaces:
          - id: b
            path: /tmp/b
            tools:
              allow: [search_text]
        """,
    )
    monkeypatch.setenv(config.ENV_CONFIG_PATH, str(cfg2))
    loaded = config.load_workspaces()
    assert loaded.get_workspace("b").path == Path("/tmp/b")
    with pytest.raises(KeyError):
        loaded.get_workspace("a")


def test_invalid_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        """
        version: 1
        workspaces:
          - id: demo
        """,
    )
    monkeypatch.setenv(config.ENV_CONFIG_PATH, str(cfg))
    with pytest.raises(ValidationError):
        config.load_workspaces()
