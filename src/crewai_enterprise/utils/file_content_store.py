from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)

DEFAULT_CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "chat_storage.db")


@dataclass
class FileContentRecord:
    file_hash: str
    extracted_text: str | None
    extracted_summary: str | None
    status: str
    filename: str | None = None
    mime_type: str | None = None
    storage_key: str | None = None
    wecom_msg_id: str | None = None
    chat_id: str | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    error_message: str | None = None
    extracted_at: str | None = None


def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(db_path, check_same_thread=False, timeout=30)


def ensure_file_content_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            wecom_msg_id TEXT,
            storage_key TEXT,
            file_hash TEXT NOT NULL,
            filename TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            page_count INTEGER,
            extracted_text TEXT,
            extracted_summary TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            extracted_at TEXT
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_file_contents_hash
        ON file_contents(file_hash)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_file_contents_chat_msg
        ON file_contents(chat_id, wecom_msg_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_file_contents_storage_key
        ON file_contents(storage_key)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_file_contents_status
        ON file_contents(status)
    """)
    conn.commit()


class FileContentStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or DEFAULT_CHAT_DB_PATH

        with _connect(self.db_path) as conn:
            ensure_file_content_schema(conn)

    def upsert_pending(
        self,
        *,
        file_hash: str,
        chat_id: str | None,
        wecom_msg_id: str | None,
        storage_key: str | None,
        filename: str | None,
        mime_type: str | None,
        size_bytes: int | None,
    ) -> None:
        with _connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO file_contents (
                    chat_id, wecom_msg_id, storage_key, file_hash,
                    filename, mime_type, size_bytes, status, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP
                )
                ON CONFLICT(file_hash) DO UPDATE SET
                    chat_id = COALESCE(file_contents.chat_id, excluded.chat_id),
                    wecom_msg_id = COALESCE(file_contents.wecom_msg_id, excluded.wecom_msg_id),
                    storage_key = COALESCE(file_contents.storage_key, excluded.storage_key),
                    filename = COALESCE(file_contents.filename, excluded.filename),
                    mime_type = COALESCE(file_contents.mime_type, excluded.mime_type),
                    size_bytes = COALESCE(file_contents.size_bytes, excluded.size_bytes),
                    status = CASE
                        WHEN file_contents.status = 'extracted' THEN file_contents.status
                        ELSE excluded.status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    chat_id,
                    wecom_msg_id,
                    storage_key,
                    file_hash,
                    filename,
                    mime_type,
                    size_bytes,
                ),
            )
            conn.commit()

    def mark_extracted(
        self,
        *,
        file_hash: str,
        extracted_text: str,
        extracted_summary: str | None,
        page_count: int | None,
        status: str = "extracted",
    ) -> None:
        with _connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE file_contents
                SET extracted_text = ?,
                    extracted_summary = ?,
                    page_count = ?,
                    status = ?,
                    error_message = NULL,
                    extracted_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE file_hash = ?
                """,
                (
                    extracted_text,
                    extracted_summary,
                    page_count,
                    status,
                    file_hash,
                ),
            )
            conn.commit()

    def mark_failed(self, *, file_hash: str, error_message: str) -> None:
        with _connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE file_contents
                SET status = 'failed',
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE file_hash = ?
                """,
                (error_message, file_hash),
            )
            conn.commit()

    def get_by_hash(self, file_hash: str) -> FileContentRecord | None:
        return self._fetch_one("file_hash = ?", (file_hash,))

    def get_by_storage_key(self, storage_key: str) -> FileContentRecord | None:
        return self._fetch_one("storage_key = ?", (storage_key,))

    def get_by_msg_id(self, wecom_msg_id: str) -> FileContentRecord | None:
        return self._fetch_one("wecom_msg_id = ?", (wecom_msg_id,))

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> FileContentRecord | None:
        with _connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT file_hash, extracted_text, extracted_summary, status,
                       filename, mime_type, storage_key, wecom_msg_id, chat_id,
                       size_bytes, page_count, error_message, extracted_at
                FROM file_contents
                WHERE {where}
                ORDER BY id DESC
                LIMIT 1
                """,
                params,
            )
            row = cursor.fetchone()
            if not row:
                return None
            return FileContentRecord(**dict(row))
