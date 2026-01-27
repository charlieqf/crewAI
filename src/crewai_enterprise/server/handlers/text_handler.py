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
    "opencode": {
        "provider": "opencode",
        "webhook_env": "WEBHOOK_OPENCODE",
        "system_prompt": "OpenCode Sisyphus Orchestrator",
    },
}


def detect_bot_type(content: str) -> str:
    """Detect which bot should handle the message based on mention."""
    content_lower = content.lower()
    if "@opencode" in content_lower:
        return "opencode"
    elif "@gemini" in content_lower or "gemini" in content_lower:
        return "gemini"
    elif "@grok" in content_lower or "grok" in content_lower:
        return "grok"
    else:
        return "gpt"  # Default to GPT


def is_clear_command(content: str) -> bool:
    """确认是否为重置指令（严格起始位判断，必须有空格分隔）"""
    tokens = content.replace("\u00a0", " ").split()
    if not tokens:
        return False

    first_token = tokens[0].lower()
    canonical_reset = "/reset"

    # 场景1：直接以 /reset 开头 (1:1 或 直接指令)
    if first_token == canonical_reset:
        return True

    # 场景2：艾特机器人后紧跟 /reset (必须有空格分隔)
    if first_token.startswith("@"):
        # @gemini /reset (必须有空格)
        if (
            len(tokens) >= 2
            and tokens[1].lower().replace("\u00a0", " ") == canonical_reset
        ):
            return True

    return False


def strip_reset_command(content: str) -> str:
    """提取重置后的提问内容（严格对齐 is_clear_command 的逻辑）"""
    tokens = content.split()
    if not tokens:
        return ""

    first_token = tokens[0].lower().replace("\u00a0", " ")
    canonical_reset = "/reset"

    # 判断哪一部分是开头的动作指令，并返回其后的内容
    if first_token == canonical_reset:
        return " ".join(tokens[1:]).strip()

    if first_token.startswith("@"):
        # @gemini /reset ... (必须有空格分隔)
        if (
            len(tokens) >= 2
            and tokens[1].lower().replace("\u00a0", " ") == canonical_reset
        ):
            return " ".join(tokens[2:]).strip()

    return content.strip()


async def process_text_message(
    bot_type: str,
    chat_id: str,
    user_name: str,
    content: str,
    webhook_url: str,
    user_id: str | None = None,
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
        sender_id = user_id or user_name
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=sender_id,
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
    bot_type: str,
    chat_id: str,
    user_name: str,
    user_id: str | None,
    webhook_url: str,
    remaining_text: str | None = None,
    wecom_msg_id: str | None = None,
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

    # [FIX] Medium finding: Use the new per-bot reset logic instead of the deleted clear_context
    sender_id = user_id or user_name
    success = context_manager.set_context_start(
        chat_id=chat_id, bot_type=bot_type, user_id=sender_id
    )
    logger.info(f"Reset context for {chat_id} bot={bot_type}: {success}")

    try:
        # 1. Send confirmation of reset
        send_webhook_message(
            webhook_url,
            f"@{user_name} 已重置针对 {bot_type.upper()} 的对话记忆，让我们重新开始吧！",
            msg_type="text",
        )

        # 2. If there's a follow-up question, process it immediately
        if remaining_text:
            logger.info(
                f"[CLEAR_FLOW] Processing follow-up question: {remaining_text[:50]}..."
            )
            await process_text_message(
                bot_type=bot_type,
                chat_id=chat_id,
                user_name=user_name,
                user_id=user_id,
                content=remaining_text,
                webhook_url=webhook_url,
                wecom_msg_id=wecom_msg_id,
                context_manager=context_manager,
            )

    except WeComWebhookError as e:
        logger.error(f"Failed to handle clear command: {e}")
