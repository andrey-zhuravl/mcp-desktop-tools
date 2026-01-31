from email.message import EmailMessage

import pytest

from mcp_desktop_tools.email import list_attachments, set_email_provider


class DummyProvider:
    def __init__(self, raw: bytes | None) -> None:
        self._raw = raw

    def get_raw_message(self, account: str, message_id: str) -> bytes | None:
        return self._raw


def build_message() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Attachment list"
    msg.set_content("Body")
    msg.add_attachment(b"payload", maintype="text", subtype="plain", filename="note.txt")
    return msg.as_bytes()


def test_list_attachments_returns_items() -> None:
    raw = build_message()
    provider = DummyProvider(raw)
    set_email_provider(provider)

    items = list_attachments("acc", "msg")

    assert len(items) == 1
    assert items[0]["filename"] == "note.txt"
    assert items[0]["mime_type"] == "text/plain"
    assert items[0]["size"] == len(b"payload")


def test_list_attachments_missing_raw() -> None:
    provider = DummyProvider(None)
    set_email_provider(provider)

    with pytest.raises(ValueError):
        list_attachments("acc", "msg")
