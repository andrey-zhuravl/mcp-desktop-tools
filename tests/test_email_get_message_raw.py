import base64
from email.message import EmailMessage

import pytest

from mcp_desktop_tools.email import get_message_raw, set_email_provider


class DummyProvider:
    def __init__(self, raw: bytes | None) -> None:
        self._raw = raw

    def get_raw_message(self, account: str, message_id: str) -> bytes | None:
        return self._raw


def build_message() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Raw test"
    msg.set_content("Raw body")
    return msg.as_bytes()


def test_get_message_raw_base64() -> None:
    raw = build_message()
    provider = DummyProvider(raw)
    set_email_provider(provider)

    result = get_message_raw("acc", "msg")

    decoded = base64.b64decode(result.encode("ascii"))
    assert decoded == raw


def test_get_message_raw_missing() -> None:
    provider = DummyProvider(None)
    set_email_provider(provider)

    with pytest.raises(ValueError):
        get_message_raw("acc", "msg")
