#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from typing import Any

import requests

from src.crewai_enterprise.utils.file_content_store import FileContentStore
from src.crewai_enterprise.utils.file_extractor import compute_file_hash, extract_text_from_file
from src.crewai_enterprise.utils.storage_manager import get_storage_manager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_file_contents")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill file_contents from stored file contexts.")
    parser.add_argument("--db-path", default=None, help="Path to chat_storage.db (defaults to CHAT_DB_PATH)")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows to process")
    parser.add_argument(
        "--since-date",
        default=None,
        help="Only process messages on/after this date (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write extraction results")
    return parser.parse_args()


def _download_file(uri: str | None, storage_key: str | None) -> bytes | None:
    if uri and uri.startswith("base64:"):
        import base64

        return base64.b64decode(uri[7:])
    if uri and uri.startswith("content:"):
        return uri[8:].encode("utf-8")

    if storage_key:
        storage = get_storage_manager()
        signed_url = storage.get_url(storage_key, expires_in_seconds=3600)
        uri = signed_url

    if not uri:
        return None

    if uri.startswith("file://"):
        path = uri[7:]
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning("Failed to read local file %s: %s", path, e)
            return None

    if uri.startswith("http://") or uri.startswith("https://"):
        try:
            resp = requests.get(uri, timeout=60)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.warning("Download failed for %s: %s", uri, e)
            return None

    return None


def _get_mime_type(content_json: dict[str, Any]) -> str:
    mime_type = content_json.get("mime")
    if mime_type:
        return mime_type
    filename = content_json.get("filename", "")
    if filename.endswith(".pdf"):
        return "application/pdf"
    if filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        return "image/jpeg"
    return "application/octet-stream"


def main() -> int:
    args = _parse_args()
    store = FileContentStore(db_path=args.db_path)
    db_path = store.db_path

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = """
        SELECT chat_id, wecom_msg_id, content, storage_key
        FROM chat_messages
        WHERE message_type = 'file'
    """
    params: list[Any] = []
    if args.since_date:
        query += " AND DATE(timestamp) >= DATE(?)"
        params.append(args.since_date)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(args.limit)
    cursor.execute(query, tuple(params))

    processed = 0
    for row in cursor.fetchall():
        chat_id, wecom_msg_id, content, storage_key = row
        if not content or not content.strip().startswith("{"):
            continue

        try:
            payload = json.loads(content)
        except Exception:
            continue

        file_hash = payload.get("hash")
        filename = payload.get("filename")
        mime_type = _get_mime_type(payload)
        uri = payload.get("uri")

        if file_hash:
            existing = store.get_by_hash(file_hash)
            if existing and existing.status == "extracted":
                continue

        file_bytes = _download_file(uri, storage_key)
        if not file_bytes:
            logger.warning("Skipping file without bytes: %s", filename)
            continue

        if not file_hash:
            file_hash = compute_file_hash(file_bytes)

        store.upsert_pending(
            file_hash=file_hash,
            chat_id=chat_id,
            wecom_msg_id=wecom_msg_id,
            storage_key=storage_key,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
        )

        result = extract_text_from_file(file_bytes, mime_type)
        if result.status == "extracted" or result.status == "partial":
            if not args.dry_run:
                store.mark_extracted(
                    file_hash=file_hash,
                    extracted_text=result.text,
                    extracted_summary=None,
                    page_count=result.page_count,
                    status=result.status,
                )
            processed += 1
        else:
            if not args.dry_run:
                store.mark_failed(
                    file_hash=file_hash,
                    error_message=result.error or "Extraction failed",
                )

    logger.info("Backfill completed. processed=%s", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
