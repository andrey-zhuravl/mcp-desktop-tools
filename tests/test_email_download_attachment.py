import base64
from email.message import EmailMessage

import pytest

from mcp_desktop_tools.email import download_attachment, list_attachments, set_email_provider


class DummyProvider:
    def __init__(self, raw: bytes | None) -> None:
        self._raw = raw

    def get_raw_message(self, account: str, message_id: str) -> bytes | None:
        return self._raw


def build_message() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Attachment download"
    msg.set_content("Body")
    msg.add_attachment(b"payload", maintype="text", subtype="plain", filename="note.txt")
    return msg.as_bytes()


def test_download_attachment_returns_payload() -> None:
    raw = build_message()
    provider = DummyProvider(raw)
    set_email_provider(provider)

    attachments = list_attachments("acc", "msg")
    attachment_id = attachments[0]["attachment_id"]

    result = download_attachment("acc", "msg", attachment_id)

    decoded = base64.b64decode(result["bytes_base64"].encode("ascii"))
    assert decoded == b"payload"
    assert result["filename"] == "note.txt"
    assert result["mime_type"] == "text/plain"
    assert result["size"] == len(b"payload")


def test_download_attachment_missing_id() -> None:
    raw = build_message()
    provider = DummyProvider(raw)
    set_email_provider(provider)

    with pytest.raises(ValueError):
        download_attachment("acc", "msg", "missing")
