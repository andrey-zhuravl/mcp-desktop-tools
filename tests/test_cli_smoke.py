from pathlib import Path
import shutil

import pytest

from mcp_desktop_tools.cli import main
from mcp_desktop_tools.config import ENV_CONFIG_PATH

RG_AVAILABLE = shutil.which("rg") is not None


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
      allow: [search_text]
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
