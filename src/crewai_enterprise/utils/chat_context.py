"""
Chat Context Manager.

Manages per-group conversation context using ChatStorageTool.
Provides sliding window context for LLM conversations.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import ChatStorageTool


# Default DB path from environment or fallback
DEFAULT_CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "chat_storage.db")

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    """Represents a chat context for LLM."""

    chat_id: str
    messages: list[dict]  # List of {"role": "user/assistant", "content": "..."}
    total_chars: int


class ChatContextManager:
    """
    Manages conversation context per group chat.

    Uses ChatStorageTool to store and retrieve message history,
    and provides formatted context for LLM calls.
    """

    def __init__(
        self,
        db_path: str | None = None,
        max_messages: int = 20,
        max_chars: int = 8000,
    ):
        """
        Initialize context manager.

        Args:
            db_path: SQLite database path for storage (uses CHAT_DB_PATH env var if not specified)
            max_messages: Maximum messages to include in context
            max_chars: Maximum total characters in context
        """
        self.max_messages = max_messages
        self.max_chars = max_chars
        self.storage = ChatStorageTool(
            backend="sqlite",
            db_path=db_path or DEFAULT_CHAT_DB_PATH,
        )

    def add_message(
        self,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        role: str = "user",
        wecom_msg_id: str | None = None,
    ) -> None:
        """
        Add a message to the chat history.

        Args:
            chat_id: Group chat ID
            sender_id: Sender user ID
            sender_name: Sender display name
            content: Message content
            role: 'user' or 'assistant'
            wecom_msg_id: Original WeCom MsgId for deduplication
        """
        # Store role in sender_name field with convention for backward compatibility:
        # For assistant: sender_name ends with "助手" or contains "bot_"
        if role == "assistant" and not (
            "助手" in sender_name or "bot_" in sender_name.lower()
        ):
            sender_name = f"{sender_name}助手"

        self.storage._run(
            action="save",
            chat_id=chat_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            role=role,
            wecom_msg_id=wecom_msg_id,
            message_type="text",
        )
        logger.debug(
            f"Added message to context: {chat_id}/{sender_name}: {content[:30]}..."
        )

    def get_context(self, chat_id: str) -> ChatContext:
        """
        Get conversation context for a chat.

        Returns recent messages formatted for LLM, respecting
        max_messages and max_chars limits.

        Args:
            chat_id: Group chat ID

        Returns:
            ChatContext with formatted messages
        """
        # Get recent messages from storage as JSON for reliable parsing
        result = self.storage._run(
            action="get_recent_json",
            chat_id=chat_id,
            limit=self.max_messages * 2,  # Get more to account for filtering
        )

        # Parse the JSON result
        messages = self._parse_storage_result(result)

        # Apply limits
        limited_messages = []
        total_chars = 0

        for msg in reversed(messages):  # Oldest first for LLM
            msg_chars = len(msg.get("content", ""))
            if total_chars + msg_chars > self.max_chars:
                break
            if len(limited_messages) >= self.max_messages:
                break
            limited_messages.append(msg)
            total_chars += msg_chars

        # Reverse back to chronological order
        limited_messages.reverse()

        return ChatContext(
            chat_id=chat_id,
            messages=limited_messages,
            total_chars=total_chars,
        )

    def clear_context(self, chat_id: str) -> int:
        """
        Clear all context for a specific chat.

        Args:
            chat_id: Group chat ID to clear

        Returns:
            Number of messages deleted
        """
        result = self.storage._run(
            action="delete_chat",
            chat_id=chat_id,
        )
        # Parse the result to extract count (format: "Deleted N messages for chat X.")
        try:
            deleted_count = int(result.split()[1])
        except (IndexError, ValueError):
            deleted_count = 0
        logger.info(f"Cleared context for chat: {chat_id}")
        return deleted_count

    def get_messages_for_llm(
        self,
        chat_id: str,
        system_prompt: str | None = None,
        current_message: str | None = None,
    ) -> list[dict]:
        """
        Get messages formatted for LLM API.

        Args:
            chat_id: Group chat ID
            system_prompt: Optional system prompt to prepend
            current_message: Current user message to append

        Returns:
            List of message dicts for LLM API
        """
        context = self.get_context(chat_id)

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Add historical messages
        for msg in context.messages:
            messages.append(
                {
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                }
            )

        # Add current message
        if current_message:
            messages.append({"role": "user", "content": current_message})

        return messages

    def _parse_storage_result(self, result: str) -> list[dict[str, str]]:
        """
        Parse the storage tool result into message list.

        Expects JSON array from get_recent_json action.
        Falls back to empty list on parse errors.
        """
        if not result or result == "[]":
            return []

        try:
            # Parse JSON array
            messages = json.loads(result)
            if not isinstance(messages, list):
                logger.warning(f"Expected list, got {type(messages)}")
                return []

            # Convert to LLM-compatible format
            formatted: list[dict[str, str]] = []
            for msg in messages:
                content = msg.get("content", "")

                # Filter out raw file JSON payloads
                if content.strip().startswith('{"uri":') and "filename" in content:
                    continue

                # Legacy support: strip [role] prefix if present (from old data)
                if content.startswith("[user]"):
                    content = content[6:]
                elif content.startswith("[assistant]"):
                    content = content[11:]

                # Prefer stored role field; fallback to sender heuristics for legacy rows
                role = msg.get("role")
                if not role:
                    sender = msg.get("sender_name", "")
                    if sender and ("助手" in sender or "bot_" in sender.lower()):
                        role = "assistant"
                    else:
                        role = "user"

                formatted.append({"role": role, "content": content})

            return formatted

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse storage result as JSON: {e}")
            return []
        except Exception as e:
            logger.warning(f"Error parsing storage result: {e}")
            return []

    def save_file(
        self,
        chat_id: str,
        sender_id: str,
        sender_name: str,
        file_uri: str,
        filename: str,
        mime_type: str,
    ) -> None:
        """
        Save file context to persistent storage.
        """
        file_info = {
            "uri": file_uri,
            "filename": filename,
            "mime": mime_type,
            "timestamp": time.time()
        }
        
        self.storage._run(
            action="save",
            chat_id=chat_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=json.dumps(file_info, ensure_ascii=False),
            message_type="file",
            role="user",
        )
        logger.info(f"Saved persistent file context for {chat_id}: {filename}")

    def get_active_file(self, chat_id: str, limit: int = 50) -> dict | None:
        """
        Get the most recent file context from storage history.
        """
        result = self.storage._run(
            action="get_recent_json",
            chat_id=chat_id,
            limit=limit,
        )
        
        if not result or result == "[]":
            return None
            
        try:
            messages = json.loads(result)
            # Find the most recent file message (iterate backwards from list)
            # Assuming list is returned oldest->newest or whatever, we just want LATEST file.
            # ChatStorageTool returns Oldest...Newest usually in JSON mode? 
            # Reversing ensures we see the LATEST message first.
            for msg in reversed(messages):
                content = msg.get("content", "")
                if content.strip().startswith('{"uri":') and "filename" in content:
                    try:
                        data = json.loads(content)
                        if "uri" in data:
                            return data
                    except:
                        continue
        except Exception:
            pass
            
        return None


# Global singleton with thread-safe access
_context_manager: ChatContextManager | None = None
_context_lock = __import__("threading").Lock()


def get_context_manager(db_path: str | None = None) -> ChatContextManager:
    """Get or create global context manager (thread-safe).

    Args:
        db_path: Database path. Uses CHAT_DB_PATH env var if not specified.
    """
    global _context_manager
    if _context_manager is None:
        with _context_lock:
            # Double-check locking pattern
            if _context_manager is None:
                _context_manager = ChatContextManager(db_path=db_path)
    return _context_manager
