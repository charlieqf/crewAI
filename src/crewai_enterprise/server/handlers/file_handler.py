"""
File Message Handler for WeCom Callback.

Handles processing of file/media messages (images, documents, etc.)
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import TYPE_CHECKING

from src.crewai_enterprise.utils.file_storage import (
    FileStorageManager,
    FileStorageError,
    get_file_manager,
)
from src.crewai_enterprise.utils.chat_context import (
    ChatContextManager,
    get_context_manager,
)
from src.crewai_enterprise.utils.file_extraction_queue import schedule_file_extraction
from src.crewai_enterprise.utils.storage_manager import get_storage_manager
from src.crewai_enterprise.tools.wecom.wecom_webhook_tool import (
    send_webhook_message,
    WeComWebhookError,
)

if TYPE_CHECKING:
    from src.crewai_enterprise.utils.wecom_message import WeComMessage

logger = logging.getLogger(__name__)


async def process_file_message(
    bot_type: str,
    chat_id: str,
    message: WeComMessage,
    user_name: str,
    webhook_url: str,
    file_manager: FileStorageManager | None = None,
    context_manager: ChatContextManager | None = None,
) -> None:
    """
    Process a file/media message.

    Downloads the file, saves to local storage, and optionally triggers LLM analysis.

    Args:
        bot_type: Bot type (gpt, gemini, grok)
        chat_id: Group chat ID
        message: Parsed WeCom message
        user_name: Sender's name
        webhook_url: Webhook URL for response
        file_manager: Optional file storage manager instance
        context_manager: Optional context manager instance
    """
    if file_manager is None:
        file_manager = get_file_manager()
    if context_manager is None:
        context_manager = get_context_manager()

    try:
        if not message.media_id:
            logger.warning(f"No media_id in file message from {user_name}")
            return

        # Download and save the file
        file_info = file_manager.download_wecom_media(
            chat_id=chat_id,
            media_id=message.media_id,
            filename=message.filename,  # Correct kwarg name
        )

        logger.info(
            f"Saved file from {user_name}: {file_info.filename} ({file_info.size_bytes} bytes)"
        )

        # Load file bytes for upload and extraction
        file_bytes = Path(file_info.file_path).read_bytes()
        mime_type = (
            mimetypes.guess_type(file_info.filename)[0] or "application/octet-stream"
        )

        storage = get_storage_manager()
        upload_res = storage.upload_file(
            file_bytes,
            file_info.filename,
            content_type=mime_type,
        )

        file_hash = schedule_file_extraction(
            chat_id=chat_id,
            wecom_msg_id=message.msg_id,
            storage_key=upload_res.key,
            filename=file_info.filename,
            mime_type=mime_type,
            file_bytes=file_bytes,
        )

        # Persist file context for later quoting/reporting
        context_manager.save_file(
            chat_id=chat_id,
            sender_id=message.from_user_id or "unknown",
            sender_name=user_name,
            file_uri=upload_res.url,
            filename=file_info.filename,
            mime_type=mime_type,
            file_hash=file_hash,
            wecom_msg_id=message.msg_id,
            bot_type=bot_type,
            storage_key=upload_res.key,
        )

        # Record a human-readable reference in context
        file_reference = f"[文件: {file_info.filename}] 已保存并上传"
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=message.from_user_id or "unknown",
            sender_name=user_name,
            content=file_reference,
            role="user",
            wecom_msg_id=message.msg_id,  # Deduplication
        )

        if message.is_image:
            # TODO: Implement GPT-4 Vision or Gemini image analysis
            logger.info("Image saved, Vision API processing to be implemented")
            send_webhook_message(
                webhook_url,
                f"@{user_name} 收到图片，已保存。图像分析功能开发中...",
                msg_type="text",
            )
        elif message.is_voice:
            # TODO: Implement speech-to-text
            logger.info("Voice saved, STT processing to be implemented")
            send_webhook_message(
                webhook_url,
                f"@{user_name} 收到语音消息，已保存。语音识别功能开发中...",
                msg_type="text",
            )
        elif message.is_video:
            logger.info("Video saved")
            send_webhook_message(
                webhook_url,
                f"@{user_name} 收到视频，已保存。",
                msg_type="text",
            )
        else:
            # Generic file (document, spreadsheet, etc.)
            # TODO: Implement document parsing with pypdf, python-docx, etc.
            logger.info("Document saved, ready for analysis")
            send_webhook_message(
                webhook_url,
                f"@{user_name} 收到文件 {file_info.filename}，已保存。",
                msg_type="text",
            )

    except FileStorageError as e:
        logger.error(f"File storage error: {e}")
        try:
            send_webhook_message(
                webhook_url,
                f"@{user_name} 文件处理失败: {str(e)[:50]}",
                msg_type="text",
            )
        except WeComWebhookError:
            pass
    except WeComWebhookError as e:
        logger.error(f"Webhook error: {e}")
    except Exception as e:
        # Catch-all to prevent silent failures in background tasks
        logger.exception(f"Unexpected error in process_file_message: {e}")
        try:
            send_webhook_message(
                webhook_url,
                f"@{user_name} 文件处理发生意外错误，请稍后重试。",
                msg_type="text",
            )
        except Exception:
            pass
