# Contributing

Thanks for contributing to MCP Desktop Tools! This document outlines the expected workflow for feature work and bug fixes.

## Development environment

1. Create a virtual environment or use pipx for isolated installs.
2. Install the project in editable mode with development dependencies:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -e .[dev]
   ```

3. Ensure `ripgrep` (`rg`) and `git` are installed and available on `PATH`.

## Quality checks

Run the full suite before sending a pull request:

```bash
ruff check .
mypy mcp_desktop_tools
pytest -q --cov=mcp_desktop_tools
```

The CI workflow in `.github/workflows/ci.yml` enforces the same commands on pushes and pull requests.

## Code style

* Follow the existing module structure; avoid introducing global state unless it is guarded by helper functions (e.g., caches).
* Keep public APIs backwards compatible when possible; add optional parameters rather than breaking call sites.
* Prefer dataclasses for structured responses and include `to_dict`/`from_dict` helpers when serialisation is required.
* Add tests for new behaviour (unit tests for pure logic, integration tests for tool flows).

## Commit and PR guidelines

* Write descriptive commit messages. For example: `repo_map: add disk cache key with tree signature`.
* Reference related issues or specs in the PR description when applicable.
* Update documentation (`README.md`, `INSTALL.md`, `PERF.md`, etc.) alongside code changes.

## Reporting issues

Please include:

* MCP Desktop Tools version (`mcp-tools --version`).
* Platform and Python version.
* Steps to reproduce, including workspace configuration snippets when relevant.

Thanks for helping us ship a fast and secure desktop MCP experience!
