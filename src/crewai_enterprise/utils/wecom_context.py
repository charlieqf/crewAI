from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime

from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import ChatStorageTool


def _truncate(text: str, limit: int = 120) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


logger = logging.getLogger(__name__)


def build_context_summary(
    messages: list[dict],
    start_time: str,
    end_time: str,
    *,
    truncated: bool = False,
) -> dict[str, str | int | bool]:
    count = len(messages)
    first_text = ""
    last_text = ""
    if messages:
        first = messages[0]
        last = messages[-1]
        first_text = _truncate(
            f"{first.get('sender', '')}: {first.get('text', '')}".strip()
        )
        last_text = _truncate(
            f"{last.get('sender', '')}: {last.get('text', '')}".strip()
        )
    return {
        "count": count,
        "start": start_time,
        "end": end_time,
        "first": first_text,
        "last": last_text,
        "truncated": truncated,
    }


def fetch_wecom_chat_context(
    chat_id: str,
    start_time: str,
    end_time: str,
    *,
    limit: int = 500,
) -> tuple[list[dict], bool]:
    hot = _fetch_hot_messages(chat_id, start_time, end_time, limit)
    archive = _fetch_archive_messages(chat_id, start_time, end_time, limit)
    combined = _merge_messages(hot, archive)
    truncated = len(combined) > limit
    if truncated:
        combined = combined[:limit]
    logger.info(
        "context fetch chat_id=%s hot=%s archive=%s total=%s truncated=%s",
        chat_id,
        len(hot),
        len(archive),
        len(combined),
        truncated,
    )
    return combined, truncated


def _fetch_hot_messages(
    chat_id: str,
    start_time: str,
    end_time: str,
    limit: int,
) -> list[dict]:
    backend = os.getenv("CHAT_STORAGE_BACKEND", "sqlite")
    tool = ChatStorageTool(backend=backend)
    raw = tool._run(
        action="get_recent_json",
        chat_id=chat_id,
        since_ts=start_time,
        limit=limit,
    )
    try:
        messages = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("failed to decode hot chat context JSON") from exc
    filtered: list[dict] = []
    for msg in messages:
        ts = msg.get("timestamp") or ""
        if ts and ts > end_time:
            continue
        filtered.append(
            {
                "created_at": ts,
                "sender": msg.get("sender_name", ""),
                "text": msg.get("content", ""),
                "wecom_msg_id": msg.get("wecom_msg_id"),
            }
        )
    return filtered


def _fetch_archive_messages(
    chat_id: str,
    start_time: str,
    end_time: str,
    limit: int,
) -> list[dict]:
    db_path = os.getenv("ARCHIVE_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"archive db not found: {db_path}")
    with sqlite3.connect(db_path, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT msgid, sender_id, room_id, content, created_at
            FROM archived_messages
            WHERE room_id = ? AND created_at >= ? AND created_at <= ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (chat_id, start_time, end_time, limit),
        )
        rows = cursor.fetchall()
    results: list[dict] = []
    for msgid, sender_id, _room_id, content, created_at in rows:
        results.append(
            {
                "created_at": str(created_at),
                "sender": sender_id or "",
                "text": content or "",
                "wecom_msg_id": msgid,
            }
        )
    return results


def _merge_messages(hot: list[dict], archive: list[dict]) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for msg in sorted(hot + archive, key=lambda m: m.get("created_at") or ""):
        msg_id = msg.get("wecom_msg_id")
        if msg_id:
            if msg_id in seen:
                continue
            seen.add(msg_id)
        merged.append(msg)
    return merged
