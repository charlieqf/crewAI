from __future__ import annotations

import os
from typing import Any

# Global cache for user project context (chat_id -> {project_path, gitlab_url})
# In production, this should be in Redis
_user_project_context: dict[str, dict[str, str]] = {}

# In-memory caches for streaming tasks and processed messages
# In production, replace with Redis/shared store
_stream_tasks: dict[str, dict[str, Any]] = {}
_processed_messages: dict[str, str] = {}  # msgid -> stream_id (dedup)

# Predefined project nicknames to bypass WeCom URL filtering
# Usage: @gemini /codebase <nickname> <question>
PROJECT_NICKNAMES = {
    "qd": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan",
    },
    "quick-deal": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan",
    },
    "project-meituan": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan",
    },
    "investorportal": {
        "project_path": "didi/investorportal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "master",
    },
}

# Bot configurations
# EncodingAESKey and Token must match WeCom admin console
BOT_CONFIGS: dict[str, dict[str, str | bool]] = {
    "gemini": {
        "provider": "gemini",
        "token_env": "GEMINI_BOT_TOKEN",
        "aes_key_env": "GEMINI_BOT_ENCODING_AES_KEY",
        "supports_file_analysis": True,
        "system_prompt": (
            "You are a helpful assistant. Respond naturally to conversations in Chinese or English. "
            "Be concise, friendly, and helpful."
        ),
    },
    "chatgpt": {
        "provider": "openai",
        "token_env": "OPENAI_BOT_TOKEN",
        "aes_key_env": "OPENAI_BOT_ENCODING_AES_KEY",
        "supports_file_analysis": True,
        "system_prompt": (
            "You are a helpful assistant. Respond naturally to conversations. "
            "Be concise, friendly, and helpful."
        ),
    },
    "grok": {
        "provider": "xai",
        "token_env": "XAI_BOT_TOKEN",
        "aes_key_env": "XAI_BOT_ENCODING_AES_KEY",
        "supports_file_analysis": False,
        "system_prompt": (
            "You are a helpful assistant. Respond naturally to conversations. "
            "Be concise, friendly, and helpful."
        ),
    },
}

__all__ = [
    "_user_project_context",
    "_stream_tasks",
    "_processed_messages",
    "PROJECT_NICKNAMES",
    "BOT_CONFIGS",
]
