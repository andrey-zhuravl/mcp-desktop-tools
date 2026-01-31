from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from email import message_from_bytes, message_from_string
from email.message import Message
from email.policy import default as default_policy
from typing import Iterable, Protocol, Sequence

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class EmailProvider(Protocol):
    def get_raw_message(self, account: str, message_id: str) -> str | bytes:
        raise NotImplementedError

    def get_message_metadata(self, account: str, message_id: str) -> dict[str, object]:
        raise NotImplementedError


_EMAIL_PROVIDER: EmailProvider | None = None


def set_email_provider(provider: EmailProvider) -> None:
    global _EMAIL_PROVIDER
    _EMAIL_PROVIDER = provider


def get_email_provider() -> EmailProvider:
    if _EMAIL_PROVIDER is None:
        raise RuntimeError("Email provider is not configured.")
    return _EMAIL_PROVIDER


def parse_raw_message(raw: str | bytes) -> Message:
    if raw is None:
        raise ValueError("Raw message payload is missing.")
    if isinstance(raw, bytes):
        return message_from_bytes(raw, policy=default_policy)
    return message_from_string(raw, policy=default_policy)


def raw_to_bytes(raw: str | bytes) -> bytes:
    if isinstance(raw, bytes):
        return raw
    return raw.encode("utf-8")


def decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        if isinstance(part.get_payload(), str):
            return part.get_payload()
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def extract_headers(message: Message) -> dict[str, str | list[str]]:
    headers: dict[str, str | list[str]] = {}
    for key, value in message.items():
        if key in headers:
            existing = headers[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                headers[key] = [existing, value]
        else:
            headers[key] = value
    return headers


@dataclass(frozen=True)
class AttachmentDescriptor:
    attachment_id: str
    filename: str | None
    mime_type: str
    size: int
    content_id: str | None
    is_inline: bool
    part: Message


def normalize_content_id(content_id: str | None) -> str | None:
    if content_id is None:
        return None
    return content_id.strip("<>")


def compute_attachment_id(part: Message, index: int) -> str:
    content_id = normalize_content_id(part.get("Content-ID")) or ""
    filename = part.get_filename() or ""
    mime_type = part.get_content_type()
    identity = f"{index}:{content_id}:{filename}:{mime_type}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def iter_attachment_parts(message: Message) -> Iterable[Message]:
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = part.get_content_disposition()
        has_filename = bool(part.get_filename())
        has_content_id = part.get("Content-ID") is not None
        if disposition in {"attachment", "inline"} or has_filename or has_content_id:
            yield part


def collect_attachments(message: Message) -> list[AttachmentDescriptor]:
    attachments: list[AttachmentDescriptor] = []
    index = 0
    for part in iter_attachment_parts(message):
        payload = part.get_payload(decode=True) or b""
        attachment_id = compute_attachment_id(part, index)
        descriptor = AttachmentDescriptor(
            attachment_id=attachment_id,
            filename=part.get_filename(),
            mime_type=part.get_content_type(),
            size=len(payload),
            content_id=normalize_content_id(part.get("Content-ID")),
            is_inline=part.get_content_disposition() == "inline",
            part=part,
        )
        attachments.append(descriptor)
        index += 1
    return attachments


def get_first_text_part(message: Message, subtype: str) -> str | None:
    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_content_type() == f"text/{subtype}":
            return decode_part_payload(part)
    return None


def validate_parts(parts: Sequence[str]) -> None:
    allowed = {"headers", "text", "html", "attachments_meta"}
    unknown = set(parts) - allowed
    if unknown:
        raise ValueError(f"Unsupported parts requested: {sorted(unknown)}")


def encode_bytes_base64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def log_payload_info(raw: str | bytes) -> None:
    raw_bytes = raw_to_bytes(raw)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    logger.info("Raw message size=%s sha256=%s", len(raw_bytes), digest)
