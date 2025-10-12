# Built-in Templates

The following templates ship with `mcp-desktop-tools` and can be referenced via `--template-id` or the MCP API.

| Template | Description | Key Variables |
|----------|-------------|---------------|
| `pyproject_min` | Minimal `pyproject.toml` plus README. | `project_name` (required), `description` (optional) |
| `python_cli_min` | Typer-based CLI skeleton with package layout. | `project_name` (required), `package_name` (auto-derived), `description` (optional) |
| `notebook_lab` | Starter Jupyter notebook with placeholder cell. | `title` (optional) |
| `readme_license` | README and MIT License pair. | `project_name` (required), `owner` (optional), `year` (optional) |

User templates stored in `~/.mcpdt/templates/<template-id>` follow the same structure. For example, to add a `garden_report` template:

```text
~/.mcpdt/templates/
  garden_report/
    template.yaml
    files/
      README.md.j2
      summary.md.j2
```

`template.yaml` declares variables and file mappings, allowing overrides of built-in templates with matching names. User templates take precedence over packaged ones at load time.
