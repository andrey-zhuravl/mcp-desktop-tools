from mcp_desktop_tools.concurrency import DEFAULT_MAX_WORKERS, resolve_max_workers


def test_resolve_max_workers_with_override() -> None:
    assert resolve_max_workers(8, None) == min(DEFAULT_MAX_WORKERS, 8)


def test_resolve_max_workers_with_env_override() -> None:
    assert resolve_max_workers(None, 6) == min(DEFAULT_MAX_WORKERS, 6)


def test_resolve_max_workers_without_overrides() -> None:
    value = resolve_max_workers(None, None)
    assert 1 <= value <= DEFAULT_MAX_WORKERS
