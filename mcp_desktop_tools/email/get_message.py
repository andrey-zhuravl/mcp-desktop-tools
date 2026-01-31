from __future__ import annotations

from typing import Sequence

from .common import (
    collect_attachments,
    extract_headers,
    get_email_provider,
    get_first_text_part,
    parse_raw_message,
    validate_parts,
)


def get_message(
    account: str,
    message_id: str,
    parts: Sequence[str] | None = None,
) -> dict[str, object]:
    selected_parts = parts or ("headers", "text", "html", "attachments_meta")
    validate_parts(selected_parts)

    provider = get_email_provider()
    raw = provider.get_raw_message(account, message_id)
    if raw is None:
        raise ValueError("Provider returned empty raw message.")

    message = parse_raw_message(raw)
    response: dict[str, object] = {}

    if "headers" in selected_parts:
        response["headers"] = extract_headers(message)
    if "text" in selected_parts:
        response["text"] = get_first_text_part(message, "plain")
    if "html" in selected_parts:
        response["html"] = get_first_text_part(message, "html")
    if "attachments_meta" in selected_parts:
        response["attachments"] = [
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

    metadata = {}
    if hasattr(provider, "get_message_metadata"):
        metadata = provider.get_message_metadata(account, message_id) or {}

    if "flags" in metadata:
        response["flags"] = metadata["flags"]
    if "thread_id" in metadata:
        response["thread_id"] = metadata["thread_id"]

    return response
