from mcp_desktop_tools.adapters import git


def test_parse_branches_current_and_tracking() -> None:
    payload = "main\x00*\x00origin/main\x00ahead 2 behind 1\x00123456\nfeature\x00 \x00\x00\x00abcdef\n"
    branches = git.parse_branches(payload)
    assert len(branches) == 2
    assert branches[0].name == "main"
    assert branches[0].is_current
    assert branches[0].ahead == 2
    assert branches[0].behind == 1
    assert branches[1].name == "feature"
    assert branches[1].ahead is None
    assert branches[1].behind is None


def test_parse_log_multiline_message() -> None:
    message = "Fix bug\n\nDetails"
    payload = "\x1e" + "\x1f".join([
        "deadbeef",
        "Alice",
        "alice@example.com",
        "2024-01-01T12:00:00+00:00",
        message,
    ])
    commits = git.parse_log(payload)
    assert len(commits) == 1
    commit = commits[0]
    assert commit.hash == "deadbeef"
    assert commit.message == message


def test_parse_shortlog() -> None:
    payload = "10\tAlice <alice@example.com>\n5\tBob <bob@example.com>\n"
    stats = git.parse_shortlog(payload)
    assert len(stats) == 2
    assert stats[0].name == "Alice"
    assert stats[0].commits == 10
    assert stats[1].email == "bob@example.com"
