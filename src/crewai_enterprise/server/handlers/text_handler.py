"""
Text Message Handler for WeCom Callback.

Handles processing of text messages and routing to appropriate LLM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.crewai_enterprise.utils.llm_router import LLMRouter, LLMError, get_router
from src.crewai_enterprise.utils.chat_context import (
    ChatContextManager,
    get_context_manager,
)
from src.crewai_enterprise.tools.wecom.wecom_webhook_tool import (
    send_webhook_message,
    WeComWebhookError,
)

if TYPE_CHECKING:
    from src.crewai_enterprise.utils.wecom_message import WeComMessage

logger = logging.getLogger(__name__)


# Bot configurations
BOT_CONFIG: dict[str, dict[str, str]] = {
    "gpt": {
        "provider": "openai",
        "webhook_env": "WEBHOOK_GPT",
        "system_prompt": "你是一个友好的AI助手，名叫GPT助手。请用简洁清晰的中文回答问题。",
    },
    "gemini": {
        "provider": "gemini",
        "webhook_env": "WEBHOOK_GEMINI",
        "system_prompt": "你是Gemini，一个擅长长文本分析和理解的AI助手。请用中文回答。",
    },
    "grok": {
        "provider": "xai",
        "webhook_env": "WEBHOOK_GROK",
        "system_prompt": "你是Grok，一个风趣幽默且知识渊博的AI助手。请用中文回答。",
    },
}


def detect_bot_type(content: str) -> str:
    """Detect which bot should handle the message based on mention."""
    content_lower = content.lower()
    if "@gemini" in content_lower or "gemini" in content_lower:
        return "gemini"
    elif "@grok" in content_lower or "grok" in content_lower:
        return "grok"
    else:
        return "gpt"  # Default to GPT


def is_clear_command(content: str) -> bool:
    """Check if the message is a context clear command."""
    clear_commands = ["/clear", "/reset", "/清空", "清空记忆", "忘记之前的"]
    content_lower = content.lower().strip()
    return any(cmd in content_lower for cmd in clear_commands)


async def process_text_message(
    bot_type: str,
    chat_id: str,
    user_name: str,
    content: str,
    webhook_url: str,
    wecom_msg_id: str | None = None,
    llm_router: LLMRouter | None = None,
    context_manager: ChatContextManager | None = None,
) -> None:
    """
    Process a text message and send LLM response via webhook.

    Args:
        bot_type: Bot type (gpt, gemini, grok)
        chat_id: Group chat ID
        user_name: Sender's name
        content: Message content
        webhook_url: Webhook URL for response
        wecom_msg_id: Original WeCom MsgId for deduplication
        llm_router: Optional LLM router instance
        context_manager: Optional context manager instance
    """
    if llm_router is None:
        llm_router = get_router()
    if context_manager is None:
        context_manager = get_context_manager()

    try:
        config = BOT_CONFIG.get(bot_type, BOT_CONFIG["gpt"])
        provider = config["provider"]
        system_prompt = config["system_prompt"]

        # Add user message to context
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=user_name,
            sender_name=user_name,
            content=content,
            role="user",
            wecom_msg_id=wecom_msg_id,
        )

        # Get conversation history
        messages = context_manager.get_messages_for_llm(
            chat_id,
            system_prompt=system_prompt,
        )

        logger.info(
            f"[LLM_REQ] bot={bot_type} provider={provider} chat={chat_id} "
            f"user={user_name} msg_count={len(messages)} content={content[:50]!r}..."
        )

        # Call LLM
        import time

        start_time = time.time()
        response = llm_router.chat(provider=provider, messages=messages)
        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"[LLM_RES] bot={bot_type} elapsed={elapsed_ms}ms "
            f"response_len={len(response.content)} content={response.content[:50]!r}..."
        )

        # Add assistant response to context
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=f"bot_{bot_type}",
            sender_name=f"{bot_type.upper()}助手",
            content=response.content,
            role="assistant",
        )

        # Send response via webhook
        send_webhook_message(
            webhook_url,
            f"@{user_name} {response.content}",
            msg_type="text",
        )

        logger.info(
            f"[SENT] bot={bot_type} chat={chat_id} user={user_name} elapsed_total={elapsed_ms}ms"
        )

    except LLMError as e:
        logger.error(
            f"[LLM_ERR] bot={bot_type} chat={chat_id} user={user_name} error={e}"
        )
        try:
            send_webhook_message(
                webhook_url,
                f"@{user_name} 抱歉，AI服务暂时不可用: {str(e)[:50]}",
                msg_type="text",
            )
        except WeComWebhookError:
            pass
    except WeComWebhookError as e:
        logger.error(
            f"[WEBHOOK_ERR] bot={bot_type} chat={chat_id} webhook={webhook_url[:30]}... error={e}"
        )
    except Exception as e:
        # Catch-all to prevent silent failures in background tasks
        logger.exception(
            f"[FATAL] bot={bot_type} chat={chat_id} user={user_name} error={e}"
        )
        try:
            send_webhook_message(
                webhook_url,
                f"@{user_name} 抱歉，发生了意外错误，请稍后重试。",
                msg_type="text",
            )
        except Exception:
            pass


async def handle_clear_command(
    chat_id: str,
    user_name: str,
    webhook_url: str,
    context_manager: ChatContextManager | None = None,
) -> None:
    """
    Handle context clear command.

    Args:
        chat_id: Group chat ID
        user_name: Sender's name
        webhook_url: Webhook URL for response
        context_manager: Optional context manager instance
    """
    if context_manager is None:
        context_manager = get_context_manager()

    deleted_count = context_manager.clear_context(chat_id)
    logger.info(f"Cleared context for {chat_id}: {deleted_count} messages")

    try:
        send_webhook_message(
            webhook_url,
            f"@{user_name} 已清空本群的对话记忆 (删除了 {deleted_count} 条消息)，让我们重新开始吧！",
            msg_type="text",
        )
    except WeComWebhookError as e:
        logger.error(f"Failed to send clear confirmation: {e}")
