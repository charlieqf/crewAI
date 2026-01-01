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
from datetime import datetime
from typing import Literal

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

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
    ] = Field(
        ...,
        description="Action: 'save', 'get_by_date', 'get_count', 'get_recent', 'get_recent_json', 'delete_chat'",
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
        self._sqlite_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = self._sqlite_conn.cursor()
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
            return self._get_recent_messages(chat_id, limit)
        elif action == "get_recent_json":
            return self._get_recent_messages_json(chat_id, limit)
        elif action == "delete_chat":
            return self._delete_chat(chat_id)
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

        timestamp = datetime.now()
        message_id = f"msg_{timestamp.strftime('%Y%m%d%H%M%S%f')}"

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
            "timestamp": timestamp.isoformat(),
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
                        timestamp,
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

    def _get_recent_messages(self, chat_id: str, limit: int = 50) -> str:
        """Get recent messages from Redis (for real-time chat participation)."""
        messages = []

        # Try Redis first (faster)
        if self._redis_client and self.backend in ("redis", "hybrid"):
            try:
                redis_key = f"chat:{chat_id}:messages"
                raw_messages = self._redis_client.lrange(redis_key, 0, limit - 1)
                for raw in raw_messages:
                    msg = json.loads(raw)
                    messages.append(msg)
                messages.reverse()  # Oldest first
                logger.info(
                    f"Retrieved {len(messages)} messages from Redis for {chat_id}"
                )
            except Exception as e:
                logger.warning(f"Redis read failed: {e}, falling back to SQLite")

        # Fallback to SQLite if Redis has no data
        if not messages and self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                """
                SELECT sender_name, content, timestamp, message_type
                FROM chat_messages
                WHERE chat_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (chat_id, limit),
            )
            rows = cursor.fetchall()
            for row in reversed(rows):
                sender_name, content, timestamp, msg_type = row
                messages.append(
                    {
                        "sender_name": sender_name,
                        "content": content,
                        "timestamp": str(timestamp),
                        "message_type": msg_type,
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

    def _get_recent_messages_json(self, chat_id: str, limit: int = 50) -> str:
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
                raw_messages = self._redis_client.lrange(redis_key, 0, limit - 1)
                for raw in raw_messages:
                    msg = json.loads(raw)
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
                messages.reverse()  # Oldest first
            except Exception as e:
                logger.warning(f"Redis read failed: {e}, falling back to SQLite")

        # Fallback to SQLite if Redis has no data
        if not messages and self._sqlite_conn and self.backend in ("sqlite", "hybrid"):
            cursor = self._sqlite_conn.cursor()
            cursor.execute(
                """
                SELECT sender_name, content, timestamp, role, wecom_msg_id, storage_key
                FROM chat_messages
                WHERE chat_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (chat_id, limit),
            )
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

    def __del__(self):
        """Close connections on cleanup."""
        if self._sqlite_conn:
            self._sqlite_conn.close()
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception:
                pass
