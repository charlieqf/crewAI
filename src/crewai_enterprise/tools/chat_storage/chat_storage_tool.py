"""
ChatStorageTool - Tool for storing and retrieving chat messages.

Supports multiple backends:
- sqlite: Persistent storage (default)
- redis: Fast in-memory cache for real-time access
- hybrid: Redis for hot data + SQLite for persistence (recommended)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Literal

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from src.crewai_enterprise.utils.file_content_store import ensure_file_content_schema

# Default DB path from environment - same as ChatContextManager
DEFAULT_CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "chat_storage.db")

logger = logging.getLogger(__name__)


class ChatStorageToolInput(BaseModel):
    """Input schema for ChatStorageTool."""

    action: Literal[
        "save",
        "get_by_date",
        "get_count",
        "get_recent",
        "get_recent_json",
        "delete_chat",
        "get_context_start",
        "set_context_start",
    ] = Field(
        ...,
        description="Action: 'save', 'get_by_date', 'get_count', 'get_recent', 'get_recent_json', 'delete_chat', 'get_context_start', 'set_context_start'",
    )
    chat_id: str = Field(..., description="Chat/Group identifier")
    # Fields for save action
    sender_id: str | None = Field(
        None, description="Sender's user ID (required for save)"
    )
    sender_name: str | None = Field(
        None, description="Sender's display name (required for save)"
    )
    content: str | None = Field(None, description="Message content (required for save)")
    message_type: str | None = Field(
        "text", description="Message type (text, image, etc.)"
    )
    role: str | None = Field("user", description="Message role: 'user' or 'assistant'")
    wecom_msg_id: str | None = Field(
        None, description="Original WeCom MsgId for deduplication"
    )
    bot_type: str | None = Field(
        None, description="Bot identifier for filtering or context resets"
    )
    storage_key: str | None = Field(
        None, description="Storage key for file-backed messages"
    )
    since_ts: str | None = Field(
        None, description="Filter messages after this timestamp"
    )
    # Fields for get actions
    date: str | None = Field(
        None, description="Date in YYYY-MM-DD format (for get_by_date and get_count)"
    )
    limit: int | None = Field(
        50, description="Number of recent messages to retrieve (for get_recent)"
    )


class ChatStorageTool(BaseTool):
    """A tool to store and retrieve chat messages with Redis+SQLite hybrid support."""

    name: str = "Chat Storage Tool"
    description: str = "Store and retrieve WeCom group chat messages for real-time chat and daily analysis."
    args_schema: type[BaseModel] = ChatStorageToolInput

    # Configuration
    backend: Literal["sqlite", "redis", "hybrid"] = Field(
        default="sqlite", description="Storage backend: sqlite, redis, or hybrid"
    )
    db_path: str = Field(
        default=DEFAULT_CHAT_DB_PATH,
        description="SQLite database path (uses CHAT_DB_PATH env var)",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0", description="Redis connection URL"
    )
    redis_ttl: int = Field(
        default=86400, description="Redis message TTL in seconds (default: 24 hours)"
    )
    max_recent_messages: int = Field(
        default=100, description="Max recent messages to keep in Redis per chat"
    )

    # Private attributes
    _sqlite_conn: sqlite3.Connection | None = None
    _redis_client: object | None = None

    def model_post_init(self, __context):
        """Initialize storage backends after model creation."""
        if self.backend in ("sqlite", "hybrid"):
            self._init_sqlite()
        if self.backend in ("redis", "hybrid"):
            self._init_redis()

    def _init_sqlite(self):
        """Initialize SQLite database and create tables if needed."""
        self._sqlite_conn = sqlite3.connect(
            self.db_path, check_same_thread=False, timeout=30
        )
        cursor = self._sqlite_conn.cursor()

        # Enable WAL mode for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT,
                wecom_msg_id TEXT,
                chat_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                sender_name TEXT NOT NULL,
                content TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                message_type TEXT DEFAULT 'text',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_date 
            ON chat_messages(chat_id, DATE(timestamp))
        """)

        # Configuration Guard: Check if we are accidentally using the archive DB
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archived_messages'"
        )
        if cursor.fetchone():
            error_msg = (
                f"CRITICAL CONFIGURATION ERROR: ChatStorageTool is pointing to an ARCHIVE database: {self.db_path}. "
                "This violates strict isolation requirements and will cause contention/corruption. "
                "Ensure CHAT_DB_PATH is NOT the same as ARCHIVE_DB_PATH."
            )
            logger.error(f"[CONFIG_GUARD] {error_msg}")
            raise RuntimeError(error_msg)

        # Safe unique index creation: remove duplicates first if any exist
        try:
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_wecom_msg_id
                ON chat_messages(wecom_msg_id)
                WHERE wecom_msg_id IS NOT NULL
            """)
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
            # OperationalError: index creation fails due to duplicates
            # IntegrityError: unique constraint violation
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                # Clean up duplicates keeping the first occurrence
                logger.warning("Duplicate wecom_msg_id detected, cleaning up...")
                cursor.execute("""
                    DELETE FROM chat_messages
                    WHERE id NOT IN (
                        SELECT MIN(id) FROM chat_messages
                        WHERE wecom_msg_id IS NOT NULL
                        GROUP BY wecom_msg_id
                    ) AND wecom_msg_id IS NOT NULL
                """)
                self._sqlite_conn.commit()
                # Retry index creation
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_wecom_msg_id
                    ON chat_messages(wecom_msg_id)
                    WHERE wecom_msg_id IS NOT NULL
                """)
                logger.info("Duplicate cleanup completed and unique index created")
            else:
                raise

        # Migration: add new columns if they don't exist
        try:
            cursor.execute(
                "ALTER TABLE chat_messages ADD COLUMN role TEXT DEFAULT 'user'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN wecom_msg_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN bot_type TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN storage_key TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Create custom_prompts table for prompt management
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_prompts (
                chat_id TEXT NOT NULL,
                bot_type TEXT NOT NULL,
                user_id TEXT NOT NULL,
                custom_prompt TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, bot_type)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_prompts_user
            ON custom_prompts(user_id)
        """)

        # [NEW] Create chat_context_settings table for /reset support
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_context_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,  -- "{chat_id}:{bot_type}"
                context_start_ts TEXT,            -- ISO format
                reset_by_user TEXT,
                reset_at TEXT,                    -- ISO format
                created_at TEXT                   -- ISO format
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_context_session 
            ON chat_context_settings(session_id)
        """)

        # File extraction cache table (shared with /file-html and quoted file analysis)
        ensure_file_content_schema(self._sqlite_conn)

        # [MIGRATION] Backfill NULL bot_type values (Mandatory for isolation)
        cursor.execute("""
            UPDATE chat_messages 
            SET bot_type = CASE
                WHEN sender_name LIKE '%gemini%' OR sender_name LIKE '%Gemini%' THEN 'gemini'
                WHEN sender_name LIKE '%chatgpt%' OR sender_name LIKE '%ChatGPT%' THEN 'chatgpt'
                WHEN sender_name LIKE '%grok%' OR sender_name LIKE '%Grok%' THEN 'grok'
                ELSE 'gemini'  -- Default fallback for historical data
            END
            WHERE bot_type IS NULL
        """)

        self._sqlite_conn.commit()
        logger.info(f"SQLite initialized: {self.db_path}")

    def _init_redis(self):
        """Initialize Redis connection."""
        try:
            import redis

            self._redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self._redis_client.ping()
            logger.info(f"Redis connected: {self.redis_url}")
        except ImportError:
            logger.warning(
                "redis package not installed. Install with: pip install redis"
            )
            if self.backend == "redis":
                raise RuntimeError("Redis backend requires redis package")
            # In hybrid mode, fall back to SQLite only
            self._redis_client = None
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            if self.backend == "redis":
                raise
            self._redis_client = None

    def _run(
        self,
        action: str,
        chat_id: str,
        sender_id: str | None = None,
        sender_name: str | None = None,
        content: str | None = None,
        message_type: str = "text",
        role: str = "user",
        wecom_msg_id: str | None = None,
        date: str | None = None,
        limit: int = 50,
        bot_type: str | None = None,
        storage_key: str | None = None,
        since_ts: str | None = None,
    ) -> str:
        """Execute the tool logic."""

        if action == "save":
            # Validate required parameters
            if not sender_id:
                raise ValueError("sender_id is required for save action")
            if not content:
                raise ValueError("content is required for save action")
            return self._save_message(
                chat_id,
                sender_id,
                sender_name or sender_id,  # Fallback to sender_id if no name
                content,
                message_type,
                role,
                wecom_msg_id,
                bot_type,
                storage_key,
            )
        elif action == "get_by_date":
            return self._get_messages_by_date(chat_id, date)
        elif action == "get_count":
            return self._get_message_count(chat_id, date)
        elif action == "get_recent":
            return self._get_recent_messages(chat_id, limit, bot_type, since_ts)
        elif action == "get_recent_json":
            return self._get_recent_messages_json(chat_id, limit, bot_type, since_ts)
        elif action == "delete_chat":
            return self._delete_chat(chat_id)
        elif action == "get_context_start":
            return self._get_context_start(chat_id, bot_type)
        elif action == "set_context_start":
            # Standardize default reset timestamp to Beijing Time (UTC+8)
            bj_now_str = datetime.now(timezone(timedelta(hours=8))).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            ts = content or bj_now_str
            return self._set_context_start(chat_id, bot_type, sender_id, ts)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _save_message(
        self,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        message_type: str,
        role: str = "user",
        wecom_msg_id: str | None = None,
        bot_type: str | None = None,
        storage_key: str | None = None,
    ) -> str:
        """Save a chat message to the storage backend(s)."""
        if not sender_id or not content:
            raise ValueError("sender_id and content are required for save action")

        # Standardize to Beijing Time (UTC+8) for consistency with Archive
        timestamp_bj = datetime.now(timezone(timedelta(hours=8)))
        message_id = f"msg_{timestamp_bj.strftime('%Y%m%d%H%M%S%f')}"

        message_data = {
            "message_id": message_id,
            "wecom_msg_id": wecom_msg_id,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "sender_name": sender_name or sender_id,
            "content": content,
            "role": role,
            "message_type": message_type,
            "bot_type": bot_type,
            "storage_key": storage_key,
            "timestamp": timestamp_bj.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # Dedup check: prefer SQLite (authoritative) for sqlite/hybrid backends
        # Known limitation: In hybrid mode, there's a small race window where concurrent
        # requests may both pass this check, causing Redis to have duplicates while SQLite
        # correctly rejects via unique index. This is acceptable for MVP low-traffic scenario.
        if wecom_msg_id and self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                "SELECT id FROM chat_messages WHERE wecom_msg_id = ?",
                (wecom_msg_id,),
            )
            if cursor.fetchone():
                logger.info(f"Duplicate message ignored: wecom_msg_id={wecom_msg_id}")
                return f"Duplicate message ignored. WeCom MsgId: {wecom_msg_id}"

        # Redis-only dedup: use SETNX to track seen message IDs (24h expiry)
        if wecom_msg_id and self._redis_client and self.backend == "redis":
            dedup_key = f"dedup:{wecom_msg_id}"
            if not self._redis_client.set(dedup_key, "1", nx=True, ex=86400):
                logger.info(
                    f"Duplicate message ignored (Redis): wecom_msg_id={wecom_msg_id}"
                )
                return f"Duplicate message ignored. WeCom MsgId: {wecom_msg_id}"

        # Save to Redis (hot data for real-time access)
        if self._redis_client and self.backend in ("redis", "hybrid"):
            try:
                redis_key = f"chat:{chat_id}:messages"
                self._redis_client.lpush(redis_key, json.dumps(message_data))
                self._redis_client.ltrim(redis_key, 0, self.max_recent_messages - 1)
                self._redis_client.expire(redis_key, self.redis_ttl)
                logger.debug(f"Message saved to Redis: {message_id}")
            except Exception as e:
                logger.error(f"Redis save failed: {e}")
                if self.backend == "redis":
                    raise

        # Save to SQLite (cold data for historical analysis)
        if self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO chat_messages (message_id, wecom_msg_id, chat_id, sender_id, sender_name, content, role, message_type, bot_type, storage_key, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        wecom_msg_id,
                        chat_id,
                        sender_id,
                        sender_name or sender_id,
                        content,
                        role,
                        message_type,
                        bot_type,
                        storage_key,
                        timestamp_bj.strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                self._sqlite_conn.commit()
                logger.debug(f"Message saved to SQLite: {message_id}")
            except sqlite3.IntegrityError:
                # Rollback to clear error state and allow subsequent writes
                self._sqlite_conn.rollback()
                logger.info(f"Duplicate message ignored: wecom_msg_id={wecom_msg_id}")
                return f"Duplicate message ignored. WeCom MsgId: {wecom_msg_id}"

        logger.info(
            f"Message saved: {message_id} in chat {chat_id} (backend: {self.backend})"
        )
        return f"Message saved successfully. ID: {message_id}"

    def _get_recent_messages(
        self,
        chat_id: str,
        limit: int = 50,
        bot_type: str | None = None,
        since_ts: str | None = None,
    ) -> str:
        """Get recent messages from Redis (for real-time chat participation)."""
        messages = []

        # Try Redis first (faster)
        if self._redis_client and self.backend in ("redis", "hybrid"):
            try:
                redis_key = f"chat:{chat_id}:messages"
                # Get more than limit to allow for filtering
                raw_messages = self._redis_client.lrange(redis_key, 0, (limit * 5) - 1)
                for raw in raw_messages:
                    msg = json.loads(raw)

                    # [FIX] Apply bot_type and since_ts filtering to Redis data
                    if bot_type and msg.get("bot_type") != bot_type:
                        continue
                    # [FIX] Medium finding: Strict filtering for resets
                    ts = msg.get("timestamp")
                    if since_ts:
                        if not ts or ts <= since_ts:
                            continue

                    messages.append(msg)
                    if len(messages) >= limit:
                        break

                messages.reverse()  # Oldest first
                logger.debug(
                    f"Retrieved {len(messages)} filtered messages from Redis for {chat_id}"
                )
            except Exception as e:
                logger.warning(f"Redis read failed: {e}, falling back to SQLite")

        # Fallback to SQLite if Redis has no data
        if not messages and self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            query = """
                SELECT sender_id, sender_name, content, timestamp, message_type, wecom_msg_id
                FROM chat_messages
                WHERE chat_id = ?
            """
            params = [chat_id]
            if bot_type:
                query += " AND bot_type = ?"
                params.append(bot_type)
            if since_ts:
                query += " AND timestamp > ?"
                params.append(since_ts)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            for row in reversed(rows):
                sender_id, sender_name, content, timestamp, msg_type, wecom_msg_id = row
                messages.append(
                    {
                        "sender_id": sender_id,
                        "sender_name": sender_name,
                        "content": content,
                        "timestamp": str(timestamp),
                        "message_type": msg_type,
                        "wecom_msg_id": wecom_msg_id,
                    }
                )
            logger.info(f"Retrieved {len(messages)} messages from SQLite for {chat_id}")

        if not messages:
            return f"没有找到 {chat_id} 的最近消息记录。"

        # Format output
        result = f"## {chat_id} 的最近 {len(messages)} 条消息\n\n"
        for msg in messages:
            ts = msg.get("timestamp", "")[:16]  # Trim to minute precision
            result += f"[{ts}] {msg['sender_name']}: {msg['content']}\n"

        return result

    def _get_recent_messages_json(
        self,
        chat_id: str,
        limit: int = 50,
        bot_type: str | None = None,
        since_ts: str | None = None,
    ) -> str:
        """
        Get recent messages in JSON format for reliable parsing.

        Returns a JSON array of message objects with role, content, sender_name.
        This method is designed for internal use by ChatContextManager.
        """
        messages: list[dict[str, str]] = []

        # Try Redis first (faster)
        if self._redis_client and self.backend in ("redis", "hybrid"):
            try:
                redis_key = f"chat:{chat_id}:messages"
                # Get more than limit to allow for filtering
                raw_messages = self._redis_client.lrange(redis_key, 0, (limit * 5) - 1)
                for raw in raw_messages:
                    msg = json.loads(raw)

                    # [FIX] Apply bot_type and since_ts filtering to Redis data
                    if bot_type and msg.get("bot_type") != bot_type:
                        continue
                    # [FIX] Medium finding: Strict filtering for resets
                    ts = msg.get("timestamp")
                    if since_ts:
                        if not ts or ts <= since_ts:
                            continue

                    # Normalize to stable schema: {sender_name, content, role, timestamp}
                    messages.append(
                        {
                            "sender_name": msg.get("sender_name", ""),
                            "content": msg.get("content", ""),
                            "role": msg.get("role", "user"),
                            "timestamp": msg.get("timestamp", ""),
                            "wecom_msg_id": msg.get("wecom_msg_id"),
                            "storage_key": msg.get("storage_key"),
                        }
                    )
                    if len(messages) >= limit:
                        break

                messages.reverse()  # Oldest first
            except Exception as e:
                logger.warning(f"Redis read failed: {e}, falling back to SQLite")

        # Fallback to SQLite if Redis has no data
        if not messages and self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            query = """
                SELECT sender_name, content, timestamp, role, wecom_msg_id, storage_key
                FROM chat_messages
                WHERE chat_id = ?
            """
            params = [chat_id]
            if bot_type:
                query += " AND bot_type = ?"
                params.append(bot_type)
            if since_ts:
                query += " AND timestamp > ?"
                params.append(since_ts)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            for row in reversed(rows):
                sender_name, content, timestamp, role, wecom_msg_id, storage_key = row
                # Same stable schema as Redis path
                messages.append(
                    {
                        "sender_name": sender_name,
                        "content": content,
                        "role": role or "user",  # Default for legacy rows
                        "timestamp": str(timestamp),
                        "wecom_msg_id": wecom_msg_id,
                        "storage_key": storage_key,
                    }
                )

        # Return as JSON string for reliable parsing
        return json.dumps(messages, ensure_ascii=False)

    def _get_messages_by_date(self, chat_id: str, date: str | None = None) -> str:
        """Get all messages for a specific date (from SQLite)."""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        if not self._sqlite_conn:
            return "SQLite backend not configured. Use 'sqlite' or 'hybrid' backend for date-based queries."

        cursor = self._sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT sender_name, content, timestamp, message_type, role
            FROM chat_messages
            WHERE chat_id = ? AND DATE(timestamp) = DATE(?)
            ORDER BY timestamp ASC
            """,
            (chat_id, date),
        )

        rows = cursor.fetchall()

        if not rows:
            return f"没有找到 {date} 的消息记录。No messages found for {date}."

        # Format messages
        messages = []
        for row in rows:
            sender_name, content, timestamp, msg_type, role = row
            role_indicator = "🤖" if role == "assistant" else ""
            time_str = (
                str(timestamp).split(" ")[1][:5]
                if " " in str(timestamp)
                else str(timestamp)[:5]
            )
            messages.append(f"[{time_str}] {role_indicator}{sender_name}: {content}")

        result = f"## {chat_id} 的对话记录 ({date})\n\n"
        result += f"共 {len(rows)} 条消息\n\n"
        result += "\n".join(messages)

        logger.info(f"Retrieved {len(rows)} messages for chat {chat_id} on {date}")
        return result

    def _get_message_count(self, chat_id: str, date: str | None = None) -> str:
        """Get message count for a specific date."""
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        if not self._sqlite_conn:
            return "SQLite backend not configured for count queries."

        cursor = self._sqlite_conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT sender_id)
            FROM chat_messages
            WHERE chat_id = ? AND DATE(timestamp) = DATE(?)
            """,
            (chat_id, date),
        )

        row = cursor.fetchone()
        msg_count, sender_count = row

        return f"Chat {chat_id} on {date}: {msg_count} messages from {sender_count} participants."

    def _delete_chat(self, chat_id: str) -> str:
        """Delete all messages for a chat."""
        deleted_count = 0

        if self._sqlite_conn:
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                "DELETE FROM chat_messages WHERE chat_id = ?",
                (chat_id,),
            )
            deleted_count = cursor.rowcount
            self._sqlite_conn.commit()

        # Also clear from Redis if available
        if self._redis_client:
            try:
                key = f"chat:{chat_id}:messages"
                self._redis_client.delete(key)
            except Exception as e:
                logger.warning(f"Failed to clear Redis cache: {e}")

        logger.info(f"Deleted {deleted_count} messages for chat: {chat_id}")
        return f"Deleted {deleted_count} messages for chat {chat_id}."

    def _get_context_start(
        self, chat_id: str, bot_type: str | None = None
    ) -> str | None:
        """Get the context start timestamp for a specific session."""
        if not self._sqlite_conn:
            return None

        if not bot_type:
            return None

        session_id = f"{chat_id}:{bot_type}"
        try:
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                "SELECT context_start_ts FROM chat_context_settings WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get context start for {session_id}: {e}")
            return None

    def _set_context_start(
        self, chat_id: str, bot_type: str | None, user_id: str | None, timestamp: str
    ) -> str:
        """Set the context start timestamp (reset) for a session."""
        if not self._sqlite_conn:
            return "Error: SQLite not configured"

        if not bot_type:
            bot_type = "gemini"

        session_id = f"{chat_id}:{bot_type}"
        try:
            cursor = self._sqlite_conn.cursor()
            # [FIX] Use ON CONFLICT DO UPDATE instead of INSERT OR REPLACE to preserve created_at reliably
            cursor.execute(
                """
                INSERT INTO chat_context_settings 
                (session_id, context_start_ts, reset_by_user, reset_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    context_start_ts = EXCLUDED.context_start_ts,
                    reset_by_user = EXCLUDED.reset_by_user,
                    reset_at = EXCLUDED.reset_at
            """,
                (session_id, timestamp, user_id or "system", timestamp, timestamp),
            )
            self._sqlite_conn.commit()
            logger.info(f"Context reset for session {session_id} at {timestamp}")
            return f"Success: Context reset for {bot_type}"
        except Exception as e:
            logger.error(f"Failed to set context start for {session_id}: {e}")
            return f"Error: {str(e)}"

    def __del__(self):
        """Close connections on cleanup."""
        if self._sqlite_conn:
            self._sqlite_conn.close()
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception:
                pass
