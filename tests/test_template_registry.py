from pathlib import Path

from mcp_desktop_tools.templates import TemplateRegistry, load_registry
import mcp_desktop_tools.templates


def test_builtin_template_available() -> None:
    registry = load_registry()
    template = registry.get("pyproject_min")
    files = template.render({"project_name": "demo"})
    paths = sorted(item.path for item in files)
    assert "pyproject.toml" in paths
    assert "README.md" in paths


def test_user_template_overrides_builtin(tmp_path: Path) -> None:
    builtin_dir = Path(mcp_desktop_tools.templates.__file__).resolve().parent
    user_dir = tmp_path / "templates"
    template_dir = user_dir / "pyproject_min"
    template_dir.mkdir(parents=True)
    (template_dir / "template.yaml").write_text(
        """
name: pyproject_min
version: 1
description: user override
files:
  - src: files/readme.j2
    dst: README.md
""",
        encoding="utf-8",
    )
    (template_dir / "files").mkdir()
    (template_dir / "files" / "readme.j2").write_text("hello\n", encoding="utf-8")

    registry = TemplateRegistry(builtin_dir, [user_dir])
    template = registry.get("pyproject_min")
    assert template.description == "user override"
    rendered = template.render({})
    assert [item.path for item in rendered] == ["README.md"]
    assert rendered[0].content == "hello\n"
