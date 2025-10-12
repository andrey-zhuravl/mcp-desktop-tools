# Scaffold Tool

The `scaffold` tool generates project structures from reusable templates or inline specifications. Templates use [Jinja2](https://jinja.palletsprojects.com/) for rendering and are stored in two locations:

- Built-in templates packaged with `mcp-desktop-tools` (`mcp_desktop_tools/templates`).
- User templates located in `~/.mcpdt/templates` (override via `MCPDT_TEMPLATES_USER_DIR`).

## Template Format

Each template resides in a directory containing `template.yaml` and a `files/` directory with `.j2` files. Example:

```yaml
name: python_cli_min
version: 1
description: "Minimal Typer CLI"
vars:
  project_name:
    required: true
  description:
    default: "Command line utility"
files:
  - src: files/pyproject.toml.j2
    dst: pyproject.toml
  - src: files/cli.py.j2
    dst: "{{ package_name }}/cli.py"
```

Variables marked `required` must be provided by the caller. Optional variables can supply defaults. Destinations and template bodies accept the full Jinja2 expression set.

## CLI Usage

Dry-run is enabled by default. Disable it explicitly with `--no-dry-run` when ready to write files.

```bash
mcp-tools --workspace ai-projects scaffold \
  --target-rel demo \
  --template-id python_cli_min \
  --var project_name=demo \
  --var description="Demo CLI" \
  --dry-run --json
```

To apply only part of a template use `--select` with the relative path inside the template (e.g. `README.md`). Inline specifications accept JSON input describing `files: [{path, content, executable?}]`.

## MCP Usage

The MCP tool expects a payload similar to:

```json
{
  "workspace_id": "ai-projects",
  "target_rel": "notes",
  "template_id": "readme_license",
  "vars": {"project_name": "Notes"},
  "dry_run": true
}
```

The response contains a `planned` list and `stats` summarising the run. Files are only written when `dry_run` is set to `false`.

## Safety and Limits

- Paths must remain inside the selected workspace; attempts to use absolute paths or `..` segments fail with `path_error`.
- Existing files are skipped unless `overwrite=true` is supplied.
- Operation limits (`scaffold_max_files`, `scaffold_max_total_bytes`) come from `workspaces.yaml` or the defaults (2000 files / 2 MB).
- The environment variable `MCPDT_SCAFFOLD_DEFAULT_DRYRUN` overrides the default dry-run mode (set to `1` for safe previews).

## GardenKeeper Example

1. Generate a meeting-notes workspace:
   ```bash
   mcp-tools --workspace garden scaffold --target-rel reports/2025-W41 --template-id readme_license --var project_name="Weekly Notes"
   ```
2. Run `mcp-tools --workspace garden repo_map --rel-path reports/2025-W41 --json` to capture the structure snapshot for the GardenKeeper report.

This workflow keeps report scaffolding reproducible while preserving safety guarantees.
