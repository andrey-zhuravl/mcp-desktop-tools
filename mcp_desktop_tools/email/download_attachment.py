from __future__ import annotations

from .common import (
    MAX_ATTACHMENT_BYTES,
    collect_attachments,
    encode_bytes_base64,
    get_email_provider,
    parse_raw_message,
)


def download_attachment(
    account: str,
    message_id: str,
    attachment_id: str,
) -> dict[str, object]:
    provider = get_email_provider()
    raw = provider.get_raw_message(account, message_id)
    if raw is None:
        raise ValueError("Provider returned empty raw message.")

    message = parse_raw_message(raw)
    for item in collect_attachments(message):
        if item.attachment_id == attachment_id:
            payload = item.part.get_payload(decode=True) or b""
            if len(payload) > MAX_ATTACHMENT_BYTES:
                raise ValueError("Attachment exceeds maximum allowed size.")
            return {
                "filename": item.filename,
                "mime_type": item.mime_type,
                "bytes_base64": encode_bytes_base64(payload),
                "size": len(payload),
            }

    raise ValueError("Attachment not found.")
