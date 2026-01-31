from __future__ import annotations

from .common import collect_attachments, get_email_provider, parse_raw_message


def list_attachments(account: str, message_id: str) -> list[dict[str, object]]:
    provider = get_email_provider()
    raw = provider.get_raw_message(account, message_id)
    if raw is None:
        raise ValueError("Provider returned empty raw message.")

    message = parse_raw_message(raw)
    return [
        {
            "attachment_id": item.attachment_id,
            "filename": item.filename,
            "mime_type": item.mime_type,
            "size": item.size,
            "content_id": item.content_id,
            "is_inline": item.is_inline,
        }
        for item in collect_attachments(message)
    ]
