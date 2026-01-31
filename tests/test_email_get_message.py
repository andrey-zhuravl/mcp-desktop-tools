from email.message import EmailMessage

import pytest

from mcp_desktop_tools.email import get_message, set_email_provider


class DummyProvider:
    def __init__(self, raw: bytes | None, metadata: dict[str, object] | None = None) -> None:
        self._raw = raw
        self._metadata = metadata or {}

    def get_raw_message(self, account: str, message_id: str) -> bytes | None:
        return self._raw

    def get_message_metadata(self, account: str, message_id: str) -> dict[str, object]:
        return self._metadata


def build_message() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Test subject"
    msg["From"] = "sender@example.com"
    msg["To"] = "receiver@example.com"
    msg.set_content("Plain text body")
    msg.add_alternative("<p>HTML body</p>", subtype="html")
    msg.add_attachment(b"attachment-data", maintype="application", subtype="octet-stream", filename="file.bin")
    return msg.as_bytes()


def test_get_message_full_parts() -> None:
    raw = build_message()
    provider = DummyProvider(raw, metadata={"flags": ["seen"], "thread_id": "t-1"})
    set_email_provider(provider)

    result = get_message("acc", "msg", parts=["headers", "text", "html", "attachments_meta"])

    headers = result["headers"]
    assert headers["Subject"] == "Test subject"
    assert "Plain text body" in result["text"]
    assert "HTML body" in result["html"]
    assert result["flags"] == ["seen"]
    assert result["thread_id"] == "t-1"
    assert len(result["attachments"]) == 1


def test_get_message_rejects_unknown_parts() -> None:
    raw = build_message()
    provider = DummyProvider(raw)
    set_email_provider(provider)

    with pytest.raises(ValueError):
        get_message("acc", "msg", parts=["unknown"])
