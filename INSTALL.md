# Installation Guide

MCP Desktop Tools targets Python 3.10 and later on Linux, macOS, and Windows. The CLI (`mcp-tools`) is distributed as a standa
rd Python package and exposes an entry point that can be installed globally via [pipx](https://pipx.pypa.io/) or into a virtua
l environment.

## Prerequisites

* Python **3.10+** with `pip`.
* External binaries:
  * [`ripgrep`](https://github.com/BurntSushi/ripgrep) (`rg`) **≥ 13.0** for the `search_text` tool.
  * [`git`](https://git-scm.com/) **≥ 2.30** for the `git_graph` tool.
* Ensure both binaries are available on `PATH`. Override discovery via `MCPDT_RG_PATH` / `MCPDT_GIT_PATH` if needed.

## Quick install with pipx

```bash
pipx install .  # run from the repository root
```

The `mcp-tools` console script will be available in your user-local executables directory (pipx ensures it is added to `PATH`).

To upgrade after pulling new commits:

```bash
pipx reinstall mcp-desktop-tools
```

## Virtual environment install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install .
```

## Configuration

1. Copy `workspaces.yaml` and populate workspace entries.
2. Optional environment overrides:
   * `MCPDT_WORKSPACES` – configuration file path.
   * `MCPDT_RG_PATH` / `MCPDT_GIT_PATH` – explicit binary paths.
   * `MCPDT_CACHE_DIR` – cache directory (default `~/.mcpdt/cache`).
   * `MCPDT_SUBPROC_TIMEOUT_MS` – timeout for `rg`/`git` invocations (default 30000ms).

## Platform notes

* **Linux/macOS** – ensure `~/.local/bin` (pipx) or the virtual environment’s `bin` directory is on `PATH`.
* **Windows** – enable long path support if working with deep repositories; pipx stores executables under `%USERPROFILE%\.local
\pipx\venvs`.
* `ripgrep` and `git` can be installed via the system package manager (`apt`, `brew`, `choco`, `winget`, etc.).

Once installed you can verify with:

```bash
mcp-tools --help
```

See [PERF.md](PERF.md) for cache/concurrency tuning and [README.md](README.md) for usage examples.
