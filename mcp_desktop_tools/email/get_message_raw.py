from __future__ import annotations

from .common import encode_bytes_base64, get_email_provider, log_payload_info


def get_message_raw(account: str, message_id: str) -> str:
    provider = get_email_provider()
    raw = provider.get_raw_message(account, message_id)
    if raw is None:
        raise ValueError("Provider returned empty raw message.")

    log_payload_info(raw)

    if isinstance(raw, bytes):
        return encode_bytes_base64(raw)
    return raw
