from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.file_content_store import FileContentStore

ARCHIVE_DB_PATH = os.getenv("ARCHIVE_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
QINIU_DOMAIN = os.getenv("QINIU_DOMAIN", "wecomfile.medmeeting.com")

MEDIA_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MEDIA_MARKERS = {"[图片]", "[文件]", "图片", "文件"}


class QuotedMediaError(Exception):
    """Fail-fast error for quoted media resolution."""


@dataclass
class QuotedMediaResult:
    status: str  # file_ctx, ocr_only, pending, not_found
    reason: str
    file_ctx: dict | None = None
    ocr_text: str | None = None
    ocr_status: str | None = None


def is_media_quote(quoted_content: str | None, quoted_filename: str | None) -> bool:
    if quoted_filename:
        lower_name = quoted_filename.lower()
        if any(lower_name.endswith(ext) for ext in MEDIA_EXTS):
            return True
    if quoted_content:
        content = quoted_content.lower()
        if any(marker in content for marker in MEDIA_MARKERS):
            return True
        if any(ext in content for ext in MEDIA_EXTS):
            return True
    return False


def resolve_quoted_media(
    *,
    chat_id: str,
    quoted_msg_id: str | None,
    quoted_filename: str | None = None,
    bot_type: str | None = None,
) -> QuotedMediaResult:
    if not quoted_msg_id and not quoted_filename:
        raise QuotedMediaError("missing quoted msg id/filename")

    ctx_manager = get_context_manager()

    # 1) Check context storage (uploaded files, file-html, etc.)
    file_ctx = None
    if quoted_msg_id:
        file_ctx = ctx_manager.get_active_file(chat_id, wecom_msg_id=quoted_msg_id, bot_type=bot_type)
        if not file_ctx and quoted_msg_id.startswith("file_"):
            file_ctx = ctx_manager.get_active_file(chat_id, wecom_msg_id=quoted_msg_id[5:], bot_type=bot_type)
    if not file_ctx and quoted_filename:
        file_ctx = ctx_manager.get_active_file(chat_id, filename=quoted_filename, bot_type=bot_type)

    if file_ctx:
        return QuotedMediaResult(status="file_ctx", reason="found in context storage", file_ctx=file_ctx)

    # 2) Check archive DB (chat_files)
    if not os.path.exists(ARCHIVE_DB_PATH):
        raise QuotedMediaError(f"archive db not found: {ARCHIVE_DB_PATH}")
    record = _fetch_chat_file_by_msgid(chat_id, quoted_msg_id) if quoted_msg_id else None
    if not record and quoted_msg_id and quoted_msg_id.startswith("file_"):
        record = _fetch_chat_file_by_msgid(chat_id, quoted_msg_id[5:])
    if not record and quoted_filename:
        record = _fetch_chat_file_by_filename(chat_id, quoted_filename)

    if record:
        file_uri = record.get("file_uri")
        filename = record.get("filename") or quoted_filename or "file"
        if not file_uri:
            return QuotedMediaResult(status="pending", reason="archive record missing file_uri")
        mime_type = _infer_mime_type(filename)
        storage_key = _parse_storage_key(file_uri)
        file_ctx = {
            "uri": file_uri,
            "filename": filename,
            "mime": mime_type,
            "storage_key": storage_key,
        }
        return QuotedMediaResult(status="file_ctx", reason="found in archive chat_files", file_ctx=file_ctx)

    # 3) OCR fallback (file_contents)
    if quoted_msg_id:
        store = FileContentStore()
        ocr_record = store.get_by_msg_id(quoted_msg_id)
        if not ocr_record and quoted_msg_id.startswith("file_"):
            ocr_record = store.get_by_msg_id(quoted_msg_id[5:])
        if ocr_record:
            if ocr_record.extracted_text:
                return QuotedMediaResult(
                    status="ocr_only",
                    reason="OCR text found without file context",
                    ocr_text=ocr_record.extracted_text,
                    ocr_status=ocr_record.status,
                )
            return QuotedMediaResult(
                status="pending",
                reason=f"OCR status={ocr_record.status}",
                ocr_status=ocr_record.status,
            )

    return QuotedMediaResult(status="not_found", reason="no file or OCR record found")


def _fetch_chat_file_by_msgid(chat_id: str, msgid: str | None) -> Optional[dict]:
    if not msgid:
        return None
    with sqlite3.connect(ARCHIVE_DB_PATH, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT msgid, room_id, sender_id, filename, file_size, file_uri, created_at
            FROM chat_files
            WHERE room_id = ? AND msgid = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, msgid),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "msgid": row[0],
            "room_id": row[1],
            "sender_id": row[2],
            "filename": row[3],
            "file_size": row[4],
            "file_uri": row[5],
            "created_at": row[6],
        }


def _fetch_chat_file_by_filename(chat_id: str, filename: str) -> Optional[dict]:
    with sqlite3.connect(ARCHIVE_DB_PATH, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT msgid, room_id, sender_id, filename, file_size, file_uri, created_at
            FROM chat_files
            WHERE room_id = ? AND filename = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, filename),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "msgid": row[0],
            "room_id": row[1],
            "sender_id": row[2],
            "filename": row[3],
            "file_size": row[4],
            "file_uri": row[5],
            "created_at": row[6],
        }


def _infer_mime_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    image_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    for ext, mime in image_types.items():
        if name.endswith(ext):
            return mime
    return "application/octet-stream"


def _parse_storage_key(file_uri: str | None) -> str | None:
    if not file_uri:
        return None
    if not file_uri.startswith("http"):
        return file_uri
    parsed = urlparse(file_uri)
    if not parsed.path:
        return None
    if QINIU_DOMAIN:
        if parsed.netloc == QINIU_DOMAIN or parsed.netloc.endswith(f".{QINIU_DOMAIN}"):
            return parsed.path.lstrip("/")
        return None
    return parsed.path.lstrip("/")
