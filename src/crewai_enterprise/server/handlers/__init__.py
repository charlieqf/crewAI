"""
WeCom Callback Server Handlers.

This package contains modular handlers for different message types.
"""

from src.crewai_enterprise.server.handlers.text_handler import (
    BOT_CONFIG,
    detect_bot_type,
    is_clear_command,
    process_text_message,
    handle_clear_command,
)
from src.crewai_enterprise.server.handlers.file_handler import process_file_message
from src.crewai_enterprise.server.handlers.opencode_handler import process_opencode_message

__all__ = [
    "BOT_CONFIG",
    "detect_bot_type",
    "is_clear_command",
    "process_text_message",
    "handle_clear_command",
    "process_file_message",
    "process_opencode_message",
]
