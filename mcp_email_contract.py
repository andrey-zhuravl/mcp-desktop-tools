from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Sequence, TypedDict, NotRequired
import base64
import os
import re
import uuid


# -----------------------------
# Ошибки (нормализованный формат)
# -----------------------------

EmailErrorCode = Literal[
    "AUTH",              # нет доступа / токен протух / неверный пароль приложения
    "PERMISSION",        # запрещено политикой/ролями/скоупами
    "NOT_FOUND",         # письмо/вложение/папка не найдены
    "INVALID_ARGUMENT",  # некорректные аргументы (folder_id, filters, draft)
    "RATE_LIMIT",        # лимиты провайдера
    "TEMPORARY",         # временная ошибка сети/сервера
    "UNSUPPORTED",       # провайдер не поддерживает операцию (или аккаунт в режиме read-only)
    "PAYLOAD_TOO_LARGE", # слишком большой raw/body/attachment для возврата в ответ
    "INTERNAL",          # баг/неожиданная ошибка
]


class EmailToolError(TypedDict):
    code: EmailErrorCode
    message: str
    details: NotRequired[dict[str, Any]]


# -----------------------------
# Сущности
# -----------------------------

ProviderType = Literal["gmail", "outlook", "imap"]


class AccountRef(TypedDict):
    """
    Нормализованная ссылка на почтовый аккаунт.
    """

    account_id: str  # внутренний ID в MCP (стабильный)
    email_address: str  # user@example.com (адрес аккаунта)
    display_name: NotRequired[str]  # человеко-читаемое имя
    provider: ProviderType  # gmail/outlook/imap
    is_default: bool  # аккаунт по умолчанию для данного user
    capabilities: dict[str, bool]  # см. ниже


class FolderRef(TypedDict):
    """
    Папка/лейбл.
    Для Gmail: label (INBOX, SENT, ... или пользовательский label).
    Для IMAP: mailbox path ("INBOX/Work").
    Для Outlook: folder id.
    """

    folder_id: str
    name: str
    path: NotRequired[str]  # для IMAP (удобно агенту/человеку)
    parent_id: NotRequired[str]
    folder_type: NotRequired[Literal["system", "user"]]
    unread_count: NotRequired[int]
    total_count: NotRequired[int]


class MessageAddress(TypedDict):
    name: NotRequired[str]
    email: str


class MessageSummary(TypedDict):
    """
    Легковесная карточка письма (для search_messages).
    """

    message_id: str
    thread_id: NotRequired[str]  # если провайдер поддерживает треды (Gmail/Outlook)
    folder_id: NotRequired[str]
    subject: NotRequired[str]
    from_: NotRequired[MessageAddress]
    to: NotRequired[list[MessageAddress]]
    cc: NotRequired[list[MessageAddress]]
    date_utc: NotRequired[str]  # ISO-8601 UTC
    snippet: NotRequired[str]  # короткий превью-текст (если доступно)
    has_attachments: NotRequired[bool]
    size_bytes: NotRequired[int]
    flags: NotRequired[dict[str, bool]]  # {"read": True, "starred": False, ...}


class MimePart(TypedDict):
    """
    Узел MIME-дерева (нормализованный).
    Важно: content не возвращаем по умолчанию (может быть огромным).
    """

    part_id: str  # например "1", "1.2" (IMAP) или provider-specific
    mime_type: str  # "text/plain", "text/html", "image/png", ...
    filename: NotRequired[str]
    disposition: NotRequired[Literal["inline", "attachment", "none"]]
    charset: NotRequired[str]
    content_id: NotRequired[str]  # для inline-изображений (cid:)
    size_bytes: NotRequired[int]
    is_attachment: bool
    children: NotRequired[list["MimePart"]]


class MessageFull(TypedDict):
    """
    Полная структура письма (get_message).
    """

    message_id: str
    thread_id: NotRequired[str]
    folder_id: NotRequired[str]

    # Заголовки (нормализованные + raw headers опционально)
    subject: NotRequired[str]
    from_: NotRequired[MessageAddress]
    reply_to: NotRequired[list[MessageAddress]]
    to: NotRequired[list[MessageAddress]]
    cc: NotRequired[list[MessageAddress]]
    bcc: NotRequired[list[MessageAddress]]
    date_utc: NotRequired[str]

    # Нормализованные тела
    body_plain: NotRequired[str]
    body_html: NotRequired[str]

    # MIME
    mime_tree: NotRequired[MimePart]
    headers: NotRequired[dict[str, str]]  # "From"/"To"/... (упрощённо, для агентов)
    raw_headers: NotRequired[str]  # "Header: value\r\n..."

    # Вложения (мета)
    attachments: NotRequired[list["AttachmentMeta"]]

    # Флаги
    flags: NotRequired[dict[str, bool]]


class AttachmentMeta(TypedDict):
    """
    Метаданные вложения.
    attachment_id обязателен: он используется в download_attachment().
    """

    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: NotRequired[int]
    is_inline: bool
    content_id: NotRequired[str]  # cid
    part_id: NotRequired[str]  # связь с mime_tree (если есть)


# -----------------------------
# Фильтры и пагинация
# -----------------------------

SortOrder = Literal["date_desc", "date_asc"]


class MessageSearchFilters(TypedDict, total=False):
    """
    Унифицированные фильтры поиска.

    Поля:
    - query: свободная строка (Gmail/Outlook поддерживают лучше всего).
             Для IMAP можно пытаться частично транслировать в SEARCH (SUBJECT/FROM/SINCE/BEFORE).
    - from_email, to_email: фильтр по адресам
    - subject_contains: подстрока
    - has_attachments: bool
    - unread: bool
    - starred: bool (если поддерживается)
    - after_utc, before_utc: ISO-8601 UTC
    - sort: сортировка (по умолчанию date_desc)
    - page_size: размер страницы (по умолчанию 25; максимум рекомендуется 100)
    - include_spam_trash: для Gmail/Outlook (если поддерживается)
    """

    query: str
    from_email: str
    to_email: str
    subject_contains: str
    has_attachments: bool
    unread: bool
    starred: bool
    after_utc: str
    before_utc: str
    sort: SortOrder
    page_size: int
    include_spam_trash: bool


class PagedMessages(TypedDict):
    items: list[MessageSummary]
    next_page_token: NotRequired[str]


# -----------------------------
# Draft (отправка/ответ)
# -----------------------------


class AttachmentInput(TypedDict, total=False):
    """
    Вложение для исходящего письма.

    Один из вариантов:
    A) content_base64 + filename + mime_type
    B) local_path (путь на стороне MCP-сервера; используется, если агент уже скачал файл туда)

    Замечания по безопасности:
    - local_path должен быть внутри разрешённой директории (например /data/mcp/email_outbox).
    - filename должен быть санитизирован.
    """

    filename: str
    mime_type: str
    content_base64: str
    local_path: str


class Draft(TypedDict, total=False):
    """
    Черновик письма.

    Минимум: to + subject + (body_plain или body_html).
    """

    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: str

    body_plain: str
    body_html: str

    attachments: list[AttachmentInput]

    # Для ответов/тредов (можно выставлять вручную, но reply_message сделает сам)
    in_reply_to: str
    references: list[str]
    thread_id: str

    # Поведение
    save_to_sent: bool  # по умолчанию True
    request_read_receipt: bool  # опционально


class SendResult(TypedDict):
    """
    Результат отправки.
    """

    message_id: NotRequired[str]  # provider message id (если известен)
    thread_id: NotRequired[str]
    provider_response: NotRequired[dict[str, Any]]


# -----------------------------
# Контракт методов
# -----------------------------


MAX_INLINE_BYTES = 10 * 1024 * 1024
MAX_RAW_BYTES = 25 * 1024 * 1024
PAGE_SIZE_DEFAULT = 25
PAGE_SIZE_MAX = 100


@dataclass
class StoredAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    content: bytes
    is_inline: bool = False
    content_id: Optional[str] = None
    part_id: Optional[str] = None

    def meta(self) -> AttachmentMeta:
        payload: AttachmentMeta = {
            "attachment_id": self.attachment_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": len(self.content),
            "is_inline": self.is_inline,
        }
        if self.content_id:
            payload["content_id"] = self.content_id
        if self.part_id:
            payload["part_id"] = self.part_id
        return payload


@dataclass
class StoredMessage:
    message_id: str
    subject: str
    from_: MessageAddress
    to: list[MessageAddress]
    cc: list[MessageAddress] = field(default_factory=list)
    bcc: list[MessageAddress] = field(default_factory=list)
    reply_to: list[MessageAddress] = field(default_factory=list)
    date_utc: str = field(default_factory=lambda: _iso_now())
    folder_id: Optional[str] = None
    thread_id: Optional[str] = None
    body_plain: Optional[str] = None
    body_html: Optional[str] = None
    mime_tree: Optional[MimePart] = None
    headers: dict[str, str] = field(default_factory=dict)
    raw_headers: Optional[str] = None
    attachments: list[StoredAttachment] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=lambda: {"read": False, "starred": False})
    labels: list[str] = field(default_factory=list)
    raw_bytes: Optional[bytes] = None

    def size_bytes(self) -> int:
        parts = [self.body_plain or "", self.body_html or "", self.raw_headers or ""]
        return sum(len(chunk.encode("utf-8")) for chunk in parts) + sum(
            len(att.content) for att in self.attachments
        )


@dataclass
class EmailMCPContract:
    """
    Референсная in-memory реализация контракта email.*.

    Она не подключается к реальным провайдерам, но обеспечивает:
    - валидацию аргументов,
    - безопасную обработку вложений,
    - единый формат ошибок.
    """

    accounts: dict[str, AccountRef]
    folders: dict[str, list[FolderRef]]
    messages: dict[str, dict[str, StoredMessage]] = field(default_factory=dict)
    user_accounts: dict[str, list[str]] = field(default_factory=dict)
    allowed_attachment_dir: Path = Path("/data/mcp/email_outbox")

    def list_accounts(self, user: str) -> list[AccountRef] | EmailToolError:
        """
        email.list_accounts(user)

        Назначение:
        - Вернуть список почтовых аккаунтов, которыми разрешено пользоваться указанному user.
        - Аккаунты заранее настроены в конфиге MCP-сервера (ограниченное число ящиков).
        - Агент выбирает аккаунт либо по is_default, либо по контексту задачи.

        Вход:
        - user: логический пользователь (например "andrei" / "ops-bot" / "billing-agent").
                Это НЕ email-адрес. Это ключ доступа/маршрутизации.

        Выход:
        - Список AccountRef:
          - account_id: строка, которая потом передаётся во все остальные методы как `account`.
          - email_address: адрес ящика.
          - provider: gmail/outlook/imap.
          - capabilities: dict[str,bool], например:
              {
                "read": True,
                "search": True,
                "raw_mime": True,
                "attachments": True,
                "send": True,
                "reply": True,
                "flags": True,
                "move": True,        # IMAP/Outlook обычно да; Gmail — через labels
                "labels": True       # Gmail/Outlook
              }

        Ошибки:
        - AUTH / PERMISSION: user не имеет прав ни на один аккаунт.
        - INTERNAL: ошибка чтения конфигов/секретов.

        Примечание:
        - Этот метод НЕ должен трогать сеть (если возможно). Максимум — лёгкая валидация конфигов.
        """
        account_ids = self.user_accounts.get(user)
        if not account_ids:
            return _error("AUTH", f"No accounts available for user '{user}'")

        available = [self.accounts[account_id] for account_id in account_ids if account_id in self.accounts]
        if not available:
            return _error("AUTH", f"No configured accounts available for user '{user}'")
        return available

    def list_folders(self, account: str) -> list[FolderRef] | EmailToolError:
        """
        email.list_folders(account)

        Назначение:
        - Вернуть дерево/список папок (IMAP) или лейблов (Gmail), или folder list (Outlook).
        - Агент использует это для навигации и выбора folder_id в search_messages.

        Вход:
        - account: account_id из list_accounts().

        Выход:
        - Список FolderRef:
          - folder_id: идентификатор папки/лейбла.
          - name: человеко-читаемое имя.
          - path: (опционально) для IMAP ("INBOX/Work").
          - parent_id: (опционально) если есть иерархия.
          - unread_count/total_count: (если провайдер отдаёт дешево; иначе опустить).

        Ошибки:
        - AUTH: нет доступа к аккаунту / токен протух.
        - TEMPORARY / RATE_LIMIT: проблемы провайдера.
        - UNSUPPORTED: если конкретный провайдер/режим не поддерживает папки.

        Нормализация:
        - Gmail: системные label’ы (INBOX, SENT, TRASH, SPAM) также возвращаются.
        - IMAP: скрытые/служебные mailboxes можно фильтровать, но лучше вернуть с пометкой folder_type="system".
        """
        if account not in self.accounts:
            return _error("AUTH", f"Unknown account '{account}'")
        return list(self.folders.get(account, []))

    def search_messages(
        self,
        account: str,
        folder: Optional[str],
        filters: MessageSearchFilters,
        page_token: Optional[str] = None,
    ) -> PagedMessages | EmailToolError:
        """
        email.search_messages(account, folder, filters, page_token)

        Назначение:
        - Найти письма в папке (или во всех папках, если folder=None),
          вернуть "карточки" MessageSummary и next_page_token.

        Вход:
        - account: account_id
        - folder:
            - folder_id из list_folders()
            - или None => поиск "по всему ящику" (если возможно).
        - filters: MessageSearchFilters (см. тип выше)
        - page_token: opaque токен для продолжения. Клиент НЕ интерпретирует.

        Выход:
        - PagedMessages:
            items: list[MessageSummary]
            next_page_token: str (если есть следующая страница)

        Семантика:
        - По умолчанию сортировка date_desc.
        - page_size по умолчанию 25, максимум 100 (рекомендуется enforce на сервере).

        Провайдерные особенности:
        - Gmail:
          - folder обычно выражается как label.
          - filters.query можно передать в Gmail search query почти напрямую.
        - Outlook:
          - использовать $search / filter по полям, аккуратно с требованиями заголовков ConsistencyLevel.
        - IMAP:
          - folder обязателен чаще всего (потому что SEARCH обычно по mailbox).
          - filters.after/before трансформировать в SINCE/BEFORE.
          - full-text query может быть ограничен (TEXT/SUBJECT/FROM), поэтому лучше частичное покрытие.

        Ошибки:
        - INVALID_ARGUMENT: неизвестный folder_id, некорректный filters.
        - AUTH / PERMISSION / TEMPORARY / RATE_LIMIT.

        Важное:
        - MessageSummary.has_attachments должен вычисляться:
          - Gmail/Outlook: по метаданным,
          - IMAP: по BODYSTRUCTURE (или лениво, если дорого) — но тогда можно опустить поле.
        """
        messages = self._get_messages(account)
        if isinstance(messages, dict) and "code" in messages:
            return messages

        if folder is not None and not self._folder_exists(account, folder):
            return _error("INVALID_ARGUMENT", f"Unknown folder '{folder}'")

        page_size = int(filters.get("page_size", PAGE_SIZE_DEFAULT) or PAGE_SIZE_DEFAULT)
        if page_size <= 0:
            return _error("INVALID_ARGUMENT", "page_size must be positive")
        page_size = min(page_size, PAGE_SIZE_MAX)

        offset = 0
        if page_token:
            token_offset = _decode_page_token(page_token)
            if token_offset is None:
                return _error("INVALID_ARGUMENT", "Invalid page_token")
            offset = token_offset

        results = []
        for message in messages.values():
            if folder and message.folder_id != folder:
                continue
            if not _matches_filters(message, filters):
                continue
            results.append(message)

        sort = filters.get("sort", "date_desc")
        reverse = sort != "date_asc"
        results.sort(key=lambda msg: _parse_iso_utc(msg.date_utc), reverse=reverse)

        page = results[offset : offset + page_size]
        summaries = [_message_summary(message) for message in page]
        payload: PagedMessages = {"items": summaries}

        next_offset = offset + page_size
        if next_offset < len(results):
            payload["next_page_token"] = _encode_page_token(next_offset)
        return payload

    def get_message(
        self,
        account: str,
        message_id: str,
        parts: Optional[Sequence[str]] = None,
    ) -> MessageFull | EmailToolError:
        """
        email.get_message(account, message_id, parts=...)

        Назначение:
        - Вернуть нормализованное представление письма (заголовки + тела + MIME-дерево + мета вложений).
        - Не возвращать "тяжёлые" байты вложений по умолчанию (их забирают через download_attachment).

        Вход:
        - account: account_id
        - message_id: id из search_messages()
        - parts: список "что именно вернуть", чтобы экономить время/трафик.
                 Если None => разумный дефолт.

        Рекомендуемые значения parts:
        - "headers"       => subject/from/to/cc/date + headers dict
        - "raw_headers"   => raw_headers строкой
        - "body_plain"    => body_plain
        - "body_html"     => body_html
        - "mime_tree"     => mime_tree (дерево частей)
        - "attachments"   => attachments (AttachmentMeta list)
        - "flags"         => флаги

        Дефолт (если parts=None):
        - headers + body_plain (если есть) + body_html (если есть) + attachments(meta) + flags
        - mime_tree можно НЕ включать по умолчанию (иногда дорого), но желательно для точной логики вложений.

        Нормализация тел:
        - Если письмо multipart/alternative:
          - body_plain берём из text/plain, body_html — из text/html.
        - Если только html:
          - body_plain можно либо опустить, либо сделать упрощённый html->text (опционально).

        Вложения:
        - attachments — это только метаданные (filename/mime_type/size/is_inline/attachment_id).
        - attachment_id должен быть пригоден для download_attachment().

        Ошибки:
        - NOT_FOUND: нет такого message_id.
        - PAYLOAD_TOO_LARGE: если клиент запросил слишком много (например raw_headers огромные) — лучше ограничить.
        - AUTH / TEMPORARY / RATE_LIMIT / INTERNAL.

        Заметка про "точный MIME":
        - Если агенту нужно 100% точное восстановление письма (включая boundary, переносы строк),
          он использует get_message_raw().
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        if parts is None:
            parts = ["headers", "body_plain", "body_html", "attachments", "flags"]

        response: MessageFull = {
            "message_id": message.message_id,
        }
        if message.thread_id:
            response["thread_id"] = message.thread_id
        if message.folder_id:
            response["folder_id"] = message.folder_id

        if "headers" in parts:
            response.update(
                {
                    "subject": message.subject,
                    "from_": message.from_,
                    "reply_to": message.reply_to,
                    "to": message.to,
                    "cc": message.cc,
                    "bcc": message.bcc,
                    "date_utc": message.date_utc,
                    "headers": dict(message.headers),
                }
            )
        if "raw_headers" in parts:
            raw_headers = message.raw_headers or _build_raw_headers(message.headers)
            if len(raw_headers.encode("utf-8")) > MAX_RAW_BYTES:
                return _error("PAYLOAD_TOO_LARGE", "raw_headers exceeds size limit")
            response["raw_headers"] = raw_headers
        if "body_plain" in parts and message.body_plain:
            response["body_plain"] = message.body_plain
        if "body_html" in parts and message.body_html:
            response["body_html"] = message.body_html
        if "mime_tree" in parts and message.mime_tree:
            response["mime_tree"] = message.mime_tree
        if "attachments" in parts:
            response["attachments"] = [attachment.meta() for attachment in message.attachments]
        if "flags" in parts:
            response["flags"] = dict(message.flags)
        return response

    def get_message_raw(self, account: str, message_id: str) -> dict[str, Any] | EmailToolError:
        """
        email.get_message_raw(account, message_id)

        Назначение:
        - Вернуть исходник письма в формате RFC822 (сырой MIME) — для точной MIME-логики,
          дебага, или для передачи в сторонние MIME-парсеры.

        Вход:
        - account: account_id
        - message_id: id письма

        Выход (рекомендуемый формат):
        {
          "message_id": "...",
          "raw_base64": "....",          # base64 от bytes RFC822
          "size_bytes": 12345,
          "content_type": "message/rfc822"
        }

        Ограничения:
        - Обязательно ограничить максимальный размер ответа (например 10–25 MB).
          Если письмо больше — вернуть PAYLOAD_TOO_LARGE с details.size_bytes.

        Провайдерные особенности:
        - IMAP: RFC822 / BODY[].
        - Gmail: messages.get(format="raw") возвращает raw base64url (нормализовать в base64).
        - Outlook: часто нужно получать MIME через /$value или special endpoints (если доступно).

        Ошибки:
        - PAYLOAD_TOO_LARGE
        - NOT_FOUND / AUTH / RATE_LIMIT / TEMPORARY
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        raw_bytes = message.raw_bytes or _build_raw_message(message)
        size_bytes = len(raw_bytes)
        if size_bytes > MAX_RAW_BYTES:
            return _error("PAYLOAD_TOO_LARGE", "raw message exceeds size limit", size_bytes=size_bytes)

        return {
            "message_id": message.message_id,
            "raw_base64": base64.b64encode(raw_bytes).decode("ascii"),
            "size_bytes": size_bytes,
            "content_type": "message/rfc822",
        }

    def list_attachments(self, account: str, message_id: str) -> list[AttachmentMeta] | EmailToolError:
        """
        email.list_attachments(account, message_id)

        Назначение:
        - Вернуть список вложений (только мета), чтобы агент мог понять:
          что скачивать, какие имена/типы, какие inline (cid), какие настоящие attachment.

        Вход:
        - account: account_id
        - message_id: id письма

        Выход:
        - list[AttachmentMeta]

        Семантика:
        - В список включаются:
          - attachment (Content-Disposition: attachment)
          - inline файлы (Content-Disposition: inline) с filename или Content-ID (например изображения в HTML)
        - attachment_id должен быть уникален в рамках message_id и пригоден для download_attachment().

        Ошибки:
        - NOT_FOUND / AUTH / TEMPORARY / RATE_LIMIT
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message
        return [attachment.meta() for attachment in message.attachments]

    def download_attachment(
        self,
        account: str,
        message_id: str,
        attachment_id: str,
        save_to: Optional[str] = None,
    ) -> dict[str, Any] | EmailToolError:
        """
        email.download_attachment(account, message_id, attachment_id)

        Назначение:
        - Скачать содержимое вложения.
        - Вариант A: вернуть байты как base64 (если размер разумный).
        - Вариант B: сохранить на диск (на стороне MCP-сервера) и вернуть путь.

        Вход:
        - account: account_id
        - message_id: id письма
        - attachment_id: id из list_attachments/get_message(attachments)
        - save_to:
            - Если указан: путь/директория для сохранения (или полный путь файла).
            - Если не указан: вернуть content_base64 (с лимитами).

        Выход (рекомендуемый формат):
        A) если save_to=None:
        {
          "attachment_id": "...",
          "filename": "...",
          "mime_type": "...",
          "size_bytes": 123,
          "content_base64": "...."
        }

        B) если save_to задан или если вложение большое:
        {
          "attachment_id": "...",
          "filename": "...",
          "mime_type": "...",
          "size_bytes": 123,
          "saved_path": "/safe/dir/filename.ext"
        }

        Безопасность:
        - Санитизировать filename (убрать ../, нулевые байты, спецсимволы).
        - Запретить запись вне разрешённой директории (jail).
        - Ограничить max bytes для возврата content_base64 (например 10MB), иначе PAYLOAD_TOO_LARGE и предложить save_to.

        Ошибки:
        - NOT_FOUND: attachment_id неверный
        - PAYLOAD_TOO_LARGE
        - INVALID_ARGUMENT: save_to небезопасен
        - AUTH / TEMPORARY / RATE_LIMIT / INTERNAL
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        attachment = next((item for item in message.attachments if item.attachment_id == attachment_id), None)
        if not attachment:
            return _error("NOT_FOUND", f"Attachment '{attachment_id}' not found")

        filename = _sanitize_filename(attachment.filename)
        payload = {
            "attachment_id": attachment.attachment_id,
            "filename": filename,
            "mime_type": attachment.mime_type,
            "size_bytes": len(attachment.content),
        }

        if save_to is None:
            if len(attachment.content) > MAX_INLINE_BYTES:
                return _error(
                    "PAYLOAD_TOO_LARGE",
                    "Attachment too large for inline download; provide save_to",
                    size_bytes=len(attachment.content),
                )
            payload["content_base64"] = base64.b64encode(attachment.content).decode("ascii")
            return payload

        resolved_path = self._resolve_save_path(save_to, filename)
        if isinstance(resolved_path, dict):
            return resolved_path

        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_bytes(attachment.content)
        payload["saved_path"] = str(resolved_path)
        return payload

    def send_message(self, account: str, draft: Draft) -> SendResult | EmailToolError:
        """
        email.send_message(account, draft)

        Назначение:
        - Отправить новое письмо (не обязательно reply).
        - Сформировать MIME (включая multipart/alternative и attachments), выполнить отправку через SMTP или API.

        Вход:
        - account: account_id
        - draft: Draft
          Минимум:
            - to: [email,...]
            - subject: str
            - body_plain или body_html
          Опционально:
            - cc/bcc
            - attachments
            - save_to_sent (default True)

        Формирование MIME (рекомендация):
        - Если есть и plain и html:
            multipart/alternative внутри multipart/mixed (если есть attachments)
        - Если есть attachments:
            multipart/mixed, где первый part — alternative или текст, дальше attachments.

        Возврат:
        - SendResult с provider message_id/thread_id если провайдер отдаёт.

        Идемпотентность (важно для агентов):
        - Рекомендуется поддержать опциональный заголовок/поле "X-Idempotency-Key"
          (можно вложить в draft через headers extension, если захотите),
          чтобы повторная отправка при ретраях не дублировала письмо.
          (Если не реализуете — хотя бы логируйте и возвращайте понятную TEMPORARY/RATE_LIMIT.)

        Ошибки:
        - INVALID_ARGUMENT: нет to/subject/body, неверные адреса, вложения битые.
        - AUTH / PERMISSION: нет прав отправки.
        - RATE_LIMIT / TEMPORARY.
        - UNSUPPORTED: аккаунт read-only или IMAP-only без SMTP.
        """
        account_ref = self.accounts.get(account)
        if not account_ref:
            return _error("AUTH", f"Unknown account '{account}'")

        to_addresses = draft.get("to") or []
        if not to_addresses or not _valid_addresses(to_addresses):
            return _error("INVALID_ARGUMENT", "draft.to must contain valid email addresses")

        subject = draft.get("subject", "").strip()
        if not subject:
            return _error("INVALID_ARGUMENT", "draft.subject is required")

        body_plain = draft.get("body_plain")
        body_html = draft.get("body_html")
        if not body_plain and not body_html:
            return _error("INVALID_ARGUMENT", "draft.body_plain or draft.body_html is required")

        message_id = str(uuid.uuid4())
        thread_id = draft.get("thread_id") or message_id

        email_message = EmailMessage()
        email_message["From"] = account_ref["email_address"]
        email_message["To"] = ", ".join(to_addresses)
        if draft.get("cc"):
            email_message["Cc"] = ", ".join(draft["cc"])
        if draft.get("bcc"):
            email_message["Bcc"] = ", ".join(draft["bcc"])
        email_message["Subject"] = subject
        email_message["Message-ID"] = f"<{message_id}@mcp.local>"
        email_message["Date"] = _format_rfc822_now()
        if draft.get("in_reply_to"):
            email_message["In-Reply-To"] = draft["in_reply_to"]
        if draft.get("references"):
            email_message["References"] = " ".join(draft["references"])

        attachments = self._prepare_attachments(draft.get("attachments", []))
        if isinstance(attachments, dict) and "code" in attachments:
            return attachments

        if body_plain and body_html:
            email_message.set_content(body_plain)
            email_message.add_alternative(body_html, subtype="html")
        elif body_html:
            email_message.add_alternative(body_html, subtype="html")
        else:
            email_message.set_content(body_plain or "")

        for attachment in attachments:
            maintype, subtype = _split_mime_type(attachment.mime_type)
            email_message.add_attachment(
                attachment.content,
                maintype=maintype,
                subtype=subtype,
                filename=attachment.filename,
            )

        raw_bytes = email_message.as_bytes()
        message = StoredMessage(
            message_id=message_id,
            subject=subject,
            from_={"email": account_ref["email_address"]},
            to=[{"email": address} for address in to_addresses],
            cc=[{"email": address} for address in draft.get("cc", [])],
            bcc=[{"email": address} for address in draft.get("bcc", [])],
            reply_to=[],
            date_utc=_iso_now(),
            folder_id=self._sent_folder_for_account(account) if draft.get("save_to_sent", True) else None,
            thread_id=thread_id,
            body_plain=body_plain,
            body_html=body_html,
            headers={
                "From": account_ref["email_address"],
                "To": ", ".join(to_addresses),
                "Subject": subject,
                "Message-ID": email_message["Message-ID"],
            },
            raw_headers=None,
            attachments=list(attachments),
            flags={"read": True, "starred": False},
            raw_bytes=raw_bytes,
        )

        self.messages.setdefault(account, {})[message_id] = message

        return {
            "message_id": message_id,
            "thread_id": thread_id,
            "provider_response": {"stored": True},
        }

    def reply_message(self, account: str, message_id: str, draft: Draft) -> SendResult | EmailToolError:
        """
        email.reply_message(account, message_id, draft)

        Назначение:
        - Удобный "ответ" без ручной сборки thread/In-Reply-To/References/получателей.
        - Метод сам:
          1) получает исходное письмо,
          2) выбирает правильных адресатов,
          3) выставляет заголовки треда,
          4) отправляет.

        Вход:
        - account: account_id
        - message_id: исходное письмо, на которое отвечаем
        - draft: Draft (обычно достаточно body_plain/body_html + (опционально) cc + attachments)
          draft.to можно игнорировать/переопределять правилами ответа (см. ниже).

        Правила выбора адресатов (нормальная дефолтная логика):
        - To:
            - если есть Reply-To => Reply-To
            - иначе From исходного письма
        - Cc:
            - если draft.cc задан => добавить его
            - иначе можно включить оригинальные To/Cc, но исключить адрес самого аккаунта (account.email_address)
              и исключить уже попавших в To (чтобы не дублировать).
        - Subject:
            - если draft.subject задан => использовать его
            - иначе: "Re: <original subject>" (не плодить "Re: Re:": нормализовать)

        Заголовки треда:
        - In-Reply-To = original Message-ID (если доступен из raw_headers/headers)
        - References  = original References + original Message-ID
        - thread_id   = original.thread_id (Gmail/Outlook)

        Цитирование:
        - Этот контракт не навязывает формат цитаты.
          Можно добавить опциональное поведение:
            draft["include_original"] = True/False
            draft["quote_style"] = "gmail"|"outlook"|"plain"
          Но если не нужно — просто отправляйте без цитаты.

        Ошибки:
        - NOT_FOUND: исходное письмо не найдено
        - AUTH / RATE_LIMIT / TEMPORARY / UNSUPPORTED
        """
        account_ref = self.accounts.get(account)
        if not account_ref:
            return _error("AUTH", f"Unknown account '{account}'")

        original = self._get_message(account, message_id)
        if isinstance(original, dict) and "code" in original:
            return original

        reply_to = original.reply_to or [original.from_]
        to_addresses = [addr["email"] for addr in reply_to]

        cc_addresses = list(draft.get("cc", []))
        if not draft.get("cc"):
            existing = {addr["email"].lower() for addr in reply_to}
            account_email = account_ref["email_address"].lower()
            for addr in original.to + original.cc:
                email = addr["email"].lower()
                if email == account_email or email in existing:
                    continue
                existing.add(email)
                cc_addresses.append(addr["email"])

        subject = draft.get("subject")
        if not subject:
            subject = _normalize_reply_subject(original.subject)

        in_reply_to = original.headers.get("Message-ID") if original.headers else None
        references = _merge_references(original.headers, in_reply_to)

        reply_draft: Draft = dict(draft)
        reply_draft["to"] = to_addresses
        reply_draft["cc"] = cc_addresses
        reply_draft["subject"] = subject
        if in_reply_to:
            reply_draft["in_reply_to"] = in_reply_to
        if references:
            reply_draft["references"] = references
        if original.thread_id:
            reply_draft["thread_id"] = original.thread_id

        return self.send_message(account, reply_draft)

    def set_flags(self, account: str, message_id: str, flags: dict[str, bool]) -> dict[str, Any] | EmailToolError:
        """
        email.set_flags(account, message_id, flags)

        Назначение:
        - Установить/снять флаги письма. Минимум:
          - read (прочитано)
          - starred (звезда)
        - Для IMAP: \\Seen / \\Flagged
        - Для Gmail: label UNREAD/STARRED (через modify)
        - Для Outlook: isRead/flag/ категорийность (частично)

        Вход:
        - account: account_id
        - message_id: id письма
        - flags: dict[str,bool], например:
            {"read": True}
            {"starred": False, "read": True}

        Выход:
        - Например:
          {"message_id": "...", "flags": {"read": True, "starred": False}}

        Ошибки:
        - UNSUPPORTED: провайдер/режим не поддерживает флаг
        - NOT_FOUND / AUTH / TEMPORARY / RATE_LIMIT
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        supported = {"read", "starred"}
        for flag in flags:
            if flag not in supported:
                return _error("UNSUPPORTED", f"Flag '{flag}' is not supported")

        message.flags.update(flags)
        return {"message_id": message.message_id, "flags": dict(message.flags)}

    def move_message(self, account: str, message_id: str, target_folder: str) -> dict[str, Any] | EmailToolError:
        """
        email.move_message(account, message_id, target_folder)

        Назначение:
        - Переместить письмо в другую папку.
        - Для Gmail часто "перемещение" — это модификация label’ов (remove INBOX/add ARCHIVE и т.п.).
          Поэтому если провайдер gmail, move_message может:
          - либо эмулировать move через labels,
          - либо вернуть UNSUPPORTED и предложить add_label/удаление label (если вы разделите операции).

        Вход:
        - account: account_id
        - message_id: id письма
        - target_folder: folder_id из list_folders()

        Выход:
        - {"message_id": "...", "moved_to": target_folder}

        IMAP детали:
        - Желательно использовать MOVE extension если доступен,
          иначе COPY + STORE \\Deleted + EXPUNGE (аккуратно: EXPUNGE может быть опасен, лучше UID EXPUNGE).

        Ошибки:
        - NOT_FOUND / AUTH / RATE_LIMIT / TEMPORARY
        - UNSUPPORTED: если "move" не реализуем в данном провайдере
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        if not self._folder_exists(account, target_folder):
            return _error("INVALID_ARGUMENT", f"Unknown folder '{target_folder}'")

        message.folder_id = target_folder
        return {"message_id": message.message_id, "moved_to": target_folder}

    def add_label(self, account: str, message_id: str, label: str) -> dict[str, Any] | EmailToolError:
        """
        email.add_label(account, message_id, label)

        (Опционально, но полезно для Gmail/Outlook categories)

        Назначение:
        - Добавить label/category к письму.

        Вход:
        - account: account_id
        - message_id: id письма
        - label: folder_id/label_id из list_folders()

        Выход:
        - {"message_id": "...", "labels": ["...","..."]} (если провайдер отдаёт список)

        Ошибки:
        - UNSUPPORTED для IMAP, если вы не мапите labels на папки.
        """
        message = self._get_message(account, message_id)
        if isinstance(message, dict) and "code" in message:
            return message

        if label not in message.labels:
            message.labels.append(label)
        return {"message_id": message.message_id, "labels": list(message.labels)}

    def _get_messages(self, account: str) -> dict[str, StoredMessage] | EmailToolError:
        if account not in self.accounts:
            return _error("AUTH", f"Unknown account '{account}'")
        return self.messages.setdefault(account, {})

    def _get_message(self, account: str, message_id: str) -> StoredMessage | EmailToolError:
        messages = self._get_messages(account)
        if isinstance(messages, dict) and "code" in messages:
            return messages
        message = messages.get(message_id)
        if not message:
            return _error("NOT_FOUND", f"Message '{message_id}' not found")
        return message

    def _prepare_attachments(self, attachments: list[AttachmentInput]) -> list[StoredAttachment] | EmailToolError:
        prepared: list[StoredAttachment] = []
        for attachment in attachments:
            if "content_base64" in attachment:
                filename = _sanitize_filename(attachment.get("filename", "attachment"))
                mime_type = attachment.get("mime_type", "application/octet-stream")
                try:
                    content = base64.b64decode(attachment["content_base64"])
                except (ValueError, TypeError):
                    return _error("INVALID_ARGUMENT", f"Invalid base64 content for attachment '{filename}'")
            elif "local_path" in attachment:
                filename = _sanitize_filename(attachment.get("filename", Path(attachment["local_path"]).name))
                mime_type = attachment.get("mime_type", "application/octet-stream")
                local_path = Path(attachment["local_path"])
                if not self._is_within_allowed_dir(local_path):
                    return _error("INVALID_ARGUMENT", "local_path is outside allowed directory")
                if not local_path.exists() or not local_path.is_file():
                    return _error("INVALID_ARGUMENT", f"Attachment path '{local_path}' does not exist")
                content = local_path.read_bytes()
            else:
                return _error("INVALID_ARGUMENT", "Attachment must include content_base64 or local_path")

            prepared.append(
                StoredAttachment(
                    attachment_id=str(uuid.uuid4()),
                    filename=filename,
                    mime_type=mime_type,
                    content=content,
                )
            )
        return prepared

    def _sent_folder_for_account(self, account: str) -> Optional[str]:
        for folder in self.folders.get(account, []):
            if folder["name"].lower() in {"sent", "sent items", "sent mail", "sents"}:
                return folder["folder_id"]
        return None

    def _folder_exists(self, account: str, folder_id: str) -> bool:
        return any(folder["folder_id"] == folder_id for folder in self.folders.get(account, []))

    def _is_within_allowed_dir(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            allowed = self.allowed_attachment_dir.resolve()
        except OSError:
            return False
        return _is_relative_to(resolved, allowed)

    def _resolve_save_path(self, save_to: str, filename: str) -> Path | EmailToolError:
        target = Path(save_to)
        if target.is_dir() or save_to.endswith(os.sep):
            target = target / filename
        if not self._is_within_allowed_dir(target):
            return _error("INVALID_ARGUMENT", "save_to is outside allowed directory")
        return target


def _matches_filters(message: StoredMessage, filters: MessageSearchFilters) -> bool:
    query = (filters.get("query") or "").lower()
    if query:
        haystack = " ".join(
            filter(
                None,
                [
                    message.subject,
                    message.body_plain or "",
                    message.body_html or "",
                    _build_snippet(message),
                ],
            )
        ).lower()
        if query not in haystack:
            return False

    if filters.get("from_email"):
        if filters["from_email"].lower() not in message.from_["email"].lower():
            return False

    if filters.get("to_email"):
        if not _address_in_list(filters["to_email"], message.to + message.cc + message.bcc):
            return False

    if filters.get("subject_contains"):
        if filters["subject_contains"].lower() not in (message.subject or "").lower():
            return False

    if filters.get("has_attachments") is True and not message.attachments:
        return False
    if filters.get("has_attachments") is False and message.attachments:
        return False

    if filters.get("unread") is True and message.flags.get("read"):
        return False
    if filters.get("unread") is False and not message.flags.get("read"):
        return False

    if filters.get("starred") is True and not message.flags.get("starred"):
        return False
    if filters.get("starred") is False and message.flags.get("starred"):
        return False

    after_utc = filters.get("after_utc")
    if after_utc and _parse_iso_utc(message.date_utc) <= _parse_iso_utc(after_utc):
        return False
    before_utc = filters.get("before_utc")
    if before_utc and _parse_iso_utc(message.date_utc) >= _parse_iso_utc(before_utc):
        return False

    return True


def _message_summary(message: StoredMessage) -> MessageSummary:
    summary: MessageSummary = {
        "message_id": message.message_id,
        "subject": message.subject,
        "from_": message.from_,
        "to": message.to,
        "cc": message.cc,
        "date_utc": message.date_utc,
        "snippet": _build_snippet(message),
        "has_attachments": bool(message.attachments),
        "size_bytes": message.size_bytes(),
        "flags": dict(message.flags),
    }
    if message.thread_id:
        summary["thread_id"] = message.thread_id
    if message.folder_id:
        summary["folder_id"] = message.folder_id
    return summary


def _build_snippet(message: StoredMessage) -> str:
    source = message.body_plain or message.body_html or ""
    snippet = re.sub(r"\s+", " ", source).strip()
    return snippet[:200]


def _address_in_list(email: str, addresses: Iterable[MessageAddress]) -> bool:
    email_lower = email.lower()
    return any(item["email"].lower() == email_lower for item in addresses)


def _valid_addresses(addresses: Iterable[str]) -> bool:
    return all("@" in address and " " not in address for address in addresses)


def _normalize_reply_subject(subject: str) -> str:
    subject = subject.strip()
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def _merge_references(headers: dict[str, str], in_reply_to: Optional[str]) -> list[str]:
    references = []
    existing = headers.get("References") if headers else None
    if existing:
        references.extend(existing.split())
    if in_reply_to:
        references.append(in_reply_to)
    return references


def _error(code: EmailErrorCode, message: str, **details: Any) -> EmailToolError:
    error: EmailToolError = {"code": code, "message": message}
    if details:
        error["details"] = details
    return error


def _sanitize_filename(filename: str) -> str:
    filename = filename.replace("\x00", "")
    filename = filename.replace("..", ".")
    filename = filename.replace("/", "_").replace("\\", "_")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)
    return filename or "attachment"


def _parse_iso_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_rfc822_now() -> str:
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")


def _encode_page_token(offset: int) -> str:
    token = f"offset:{offset}".encode("utf-8")
    return base64.urlsafe_b64encode(token).decode("ascii")


def _decode_page_token(token: str) -> Optional[int]:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not decoded.startswith("offset:"):
        return None
    try:
        return int(decoded.split(":", 1)[1])
    except ValueError:
        return None


def _build_raw_headers(headers: dict[str, str]) -> str:
    return "\r\n".join(f"{key}: {value}" for key, value in headers.items())


def _build_raw_message(message: StoredMessage) -> bytes:
    email_message = EmailMessage()
    for key, value in message.headers.items():
        email_message[key] = value
    if message.body_plain and message.body_html:
        email_message.set_content(message.body_plain)
        email_message.add_alternative(message.body_html, subtype="html")
    elif message.body_html:
        email_message.add_alternative(message.body_html, subtype="html")
    else:
        email_message.set_content(message.body_plain or "")

    for attachment in message.attachments:
        maintype, subtype = _split_mime_type(attachment.mime_type)
        email_message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )
    return email_message.as_bytes()


def _split_mime_type(mime_type: str) -> tuple[str, str]:
    if "/" not in mime_type:
        return "application", "octet-stream"
    maintype, subtype = mime_type.split("/", 1)
    return maintype or "application", subtype or "octet-stream"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False
