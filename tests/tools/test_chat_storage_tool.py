"""
Unit tests for ChatStorageTool - database operations for chat message storage.

Following TDD approach - tests written before implementation.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from pydantic import ValidationError


class TestChatMessage(unittest.TestCase):
    """Tests for ChatMessage data model."""

    def test_create_chat_message(self):
        """Test creating a chat message with all fields."""
        from src.crewai_enterprise.models.chat_message import ChatMessage

        msg = ChatMessage(
            message_id="msg_001",
            chat_id="group_123",
            sender_id="user_456",
            sender_name="张三",
            content="大家好，今天的会议几点开始？",
            timestamp=datetime.now(),
            message_type="text",
        )

        self.assertEqual(msg.message_id, "msg_001")
        self.assertEqual(msg.sender_name, "张三")
        self.assertEqual(msg.message_type, "text")

    def test_message_requires_content(self):
        """Test that message content is required."""
        from src.crewai_enterprise.models.chat_message import ChatMessage

        with self.assertRaises(ValidationError):
            ChatMessage(
                message_id="msg_001",
                chat_id="group_123",
                sender_id="user_456",
                sender_name="张三",
                # content is missing
                timestamp=datetime.now(),
                message_type="text",
            )


class TestChatStorageTool(unittest.TestCase):
    """Tests for ChatStorageTool functionality."""

    def setUp(self):
        """Set up test database."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageTool,
        )

        # Use in-memory SQLite for testing
        self.tool = ChatStorageTool(backend="sqlite", db_path=":memory:")

    def test_save_message(self):
        """Test saving a chat message to database."""
        result = self.tool._run(
            action="save",
            chat_id="group_123",
            sender_id="user_456",
            sender_name="张三",
            content="测试消息",
            message_type="text",
        )

        self.assertIn("saved", result.lower())

    def test_get_messages_by_date(self):
        """Test retrieving messages for a specific date."""
        # Save some messages
        self.tool._run(
            action="save",
            chat_id="group_123",
            sender_id="user_456",
            sender_name="张三",
            content="早上好",
            message_type="text",
        )
        self.tool._run(
            action="save",
            chat_id="group_123",
            sender_id="user_789",
            sender_name="李四",
            content="早上好！",
            message_type="text",
        )

        # Retrieve messages
        result = self.tool._run(
            action="get_by_date",
            chat_id="group_123",
            date=datetime.now().strftime("%Y-%m-%d"),
        )

        self.assertIn("早上好", result)
        self.assertIn("张三", result)
        self.assertIn("李四", result)

    def test_get_messages_empty_day(self):
        """Test retrieving messages when none exist."""
        result = self.tool._run(
            action="get_by_date",
            chat_id="group_123",
            date="2020-01-01",  # A date with no messages
        )

        self.assertIn("没有", result.lower()) or self.assertIn(
            "no messages", result.lower()
        )

    def test_get_message_count(self):
        """Test getting message count for a chat."""
        # Save messages
        for i in range(5):
            self.tool._run(
                action="save",
                chat_id="group_123",
                sender_id=f"user_{i}",
                sender_name=f"用户{i}",
                content=f"消息{i}",
                message_type="text",
            )

        result = self.tool._run(
            action="get_count",
            chat_id="group_123",
            date=datetime.now().strftime("%Y-%m-%d"),
        )

        self.assertIn("5", result)


class TestChatStorageToolInput(unittest.TestCase):
    """Tests for input validation."""

    def test_valid_save_input(self):
        """Test valid input for saving message."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageToolInput,
        )

        input_data = ChatStorageToolInput(
            action="save",
            chat_id="group_123",
            sender_id="user_456",
            sender_name="张三",
            content="测试消息",
            message_type="text",
        )
        self.assertEqual(input_data.action, "save")

    def test_valid_get_by_date_input(self):
        """Test valid input for getting messages by date."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageToolInput,
        )

        input_data = ChatStorageToolInput(
            action="get_by_date", chat_id="group_123", date="2024-12-25"
        )
        self.assertEqual(input_data.action, "get_by_date")

    def test_valid_get_recent_input(self):
        """Test valid input for getting recent messages."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageToolInput,
        )

        input_data = ChatStorageToolInput(
            action="get_recent", chat_id="group_123", limit=50
        )
        self.assertEqual(input_data.action, "get_recent")

    def test_invalid_action(self):
        """Test that invalid actions are rejected."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageToolInput,
        )

        with self.assertRaises(ValidationError):
            ChatStorageToolInput(action="invalid_action", chat_id="group_123")


class TestChatStorageToolBackends(unittest.TestCase):
    """Tests for different storage backends."""

    def test_sqlite_backend_initialization(self):
        """Test SQLite backend can be initialized."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageTool,
        )

        tool = ChatStorageTool(backend="sqlite", db_path=":memory:")
        self.assertEqual(tool.backend, "sqlite")
        self.assertIsNotNone(tool._sqlite_conn)

    def test_hybrid_backend_with_sqlite_fallback(self):
        """Test hybrid backend falls back to SQLite when Redis unavailable."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageTool,
        )

        # Use invalid Redis URL to test fallback
        tool = ChatStorageTool(
            backend="hybrid", db_path=":memory:", redis_url="redis://invalid:6379/0"
        )

        # Should still work with SQLite
        result = tool._run(
            action="save",
            chat_id="group_123",
            sender_id="user_456",
            sender_name="张三",
            content="测试消息",
            message_type="text",
        )
        self.assertIn("saved", result.lower())

    def test_get_recent_messages(self):
        """Test getting recent messages with SQLite fallback."""
        from src.crewai_enterprise.tools.chat_storage.chat_storage_tool import (
            ChatStorageTool,
        )

        tool = ChatStorageTool(backend="sqlite", db_path=":memory:")

        # Save messages
        for i in range(10):
            tool._run(
                action="save",
                chat_id="group_123",
                sender_id=f"user_{i}",
                sender_name=f"用户{i}",
                content=f"消息{i}",
                message_type="text",
            )

        # Get recent messages
        result = tool._run(
            action="get_recent",
            chat_id="group_123",
            limit=5,
        )

        self.assertIn("消息", result)
        self.assertIn("用户", result)


if __name__ == "__main__":
    unittest.main()
