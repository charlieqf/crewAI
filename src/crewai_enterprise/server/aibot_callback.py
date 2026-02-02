"""
AI Bot Callback Handler for WeCom Intelligent Robots.

Handles callbacks from 3 independent intelligent robots (gemini/chatgpt/grok).
Each robot has its own callback endpoint and connects to its respective LLM.

Key differences from self-built application:
- Uses JSON encryption (not XML)
- receiveid is empty string
- Supports streaming responses
- Direct callback response (no webhook needed)

Streaming Flow:
1. User sends message -> WeCom calls POST /ai-bot/{bot_type}
2. We immediately store task with finish=False & return "思考中..."
3. LLM is called asynchronously, result stored when complete
4. WeCom polls with msgtype=stream, we return current progress
5. When LLM completes, we return finish=True with full response
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
import time
from urllib.parse import urlparse
from typing import Any

import requests

from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.file_extraction_queue import schedule_file_extraction
from src.crewai_enterprise.utils.storage_manager import get_storage_manager
from src.crewai_enterprise.server.opencode_client import OpenCodeClient
from src.crewai_enterprise.server.session_store import SessionStore
from src.crewai_enterprise.server.handlers.aibot import (
    BOT_CONFIGS,
    PROJECT_NICKNAMES,
    _decrypt_media,
    _encrypt_response,
    _extract_chat_id,
    _extract_file_info,
    _extract_image_urls_from_mixed,
    _extract_msg_id,
    _extract_quote_content,
    _extract_text_from_mixed,
    _generate_stream_id,
    _get_bot_aes_key,
    _get_bot_crypto,
    _has_image_in_mixed,
    _make_text_stream,
    _processed_messages,
    _sanitize_filename,
    _sanitize_text,
    _stream_tasks,
    _user_project_context,
    _detect_daily_report_intent,
    _upload_image_to_ucs,
    _call_llm_async,
    _call_vision_llm_async,
)
from src.crewai_enterprise.server.handlers.aibot.commands import _handle_prompt_command
from src.crewai_enterprise.server.handlers.aibot.llm_orchestrator import (
    _process_llm_file_output,
)
from src.crewai_enterprise.server.handlers.task_handler import handle_task_command

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

_opencode_client: OpenCodeClient | None = None
_opencode_session_store: SessionStore | None = None


def register_aibot_routes(app: FastAPI) -> None:
    """Register AI Bot callback routes to the FastAPI app."""

    @app.get("/ai-bot/{bot_type}", response_class=PlainTextResponse)
    async def verify_url(
        bot_type: str,
        msg_signature: str = Query(..., description="Message signature"),
        timestamp: str = Query(..., description="Timestamp"),
        nonce: str = Query(..., description="Nonce"),
        echostr: str = Query(..., description="Echo string to decrypt and return"),
    ) -> str:
        """URL verification endpoint for WeCom intelligent robot callback configuration."""
        logger.info(f"[AIBOT_VERIFY] bot={bot_type} Verifying callback URL")

        if bot_type not in BOT_CONFIGS:
            raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_type}")

        try:
            crypto = _get_bot_crypto(bot_type)
            ret, decrypted_echostr = crypto.VerifyURL(
                msg_signature, timestamp, nonce, echostr
            )

            if ret != 0:
                logger.error(
                    f"[AIBOT_VERIFY] bot={bot_type} Verification failed: {ret}"
                )
                raise HTTPException(status_code=403, detail="Verification failed")

            logger.info(f"[AIBOT_VERIFY] bot={bot_type} Verification successful")
            if isinstance(decrypted_echostr, bytes):
                return decrypted_echostr.decode("utf-8")
            if decrypted_echostr is None:
                return ""
            return str(decrypted_echostr)

        except ValueError as e:
            logger.error(f"[AIBOT_VERIFY] bot={bot_type} Config error: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/ai-bot/{bot_type}")
    async def handle_message(
        request: Request,
        bot_type: str,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
    ) -> Response:
        """Handle incoming messages from WeCom intelligent robot."""
        print(
            f"--- [AIBOT_ENTRY] bot={bot_type} signature={msg_signature[:10]}... timestamp={timestamp} ---",
            flush=True,
        )
        if bot_type not in BOT_CONFIGS:
            raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_type}")

        try:
            crypto = _get_bot_crypto(bot_type)
            post_data = await request.body()

            # Decrypt message
            ret, decrypted_msg = crypto.DecryptMsg(
                post_data, msg_signature, timestamp, nonce
            )

            if ret != 0:
                logger.error(f"[AIBOT_MSG] bot={bot_type} Decryption failed: {ret}")
                raise HTTPException(status_code=400, detail="Decryption failed")

            if not decrypted_msg:
                raise HTTPException(status_code=400, detail="Empty decrypted payload")

            payload = (
                decrypted_msg.decode("utf-8")
                if isinstance(decrypted_msg, (bytes, bytearray))
                else decrypted_msg
            )
            data = json.loads(payload)
            msgtype = data.get("msgtype", "")
            response_url = data.get("response_url")

            logger.info(
                f"[AIBOT_RECV] bot={bot_type} msgtype={msgtype} "
                f"data={json.dumps(data, ensure_ascii=False)[:200]}"
            )

            if msgtype == "text":
                return await _handle_text_message(
                    bot_type, data, nonce, timestamp, response_url=response_url
                )
            elif msgtype == "stream":
                return await _handle_stream_refresh(bot_type, data, nonce, timestamp)
            elif msgtype == "mixed":
                # Handle mixed messages (text + image combination)
                return await _handle_mixed_message(
                    bot_type, data, nonce, timestamp, response_url=response_url
                )
            elif msgtype == "image":
                # Handle image-only messages
                return await _handle_image_message(
                    bot_type, data, nonce, timestamp, response_url=response_url
                )
            elif msgtype == "file":
                # Handle file messages (PDF, Excel, etc.)
                return await _handle_file_message(
                    bot_type, data, nonce, timestamp, response_url=response_url
                )
            elif msgtype == "event":
                # Handle events (e.g., bot added to group)
                logger.info(f"[AIBOT_EVENT] bot={bot_type} event={data}")
                return Response(content="success", media_type="text/plain")
            else:
                logger.warning(
                    f"[AIBOT_MSG] bot={bot_type} Unsupported msgtype: {msgtype}"
                )
                return Response(content="success", media_type="text/plain")

        except json.JSONDecodeError as e:
            logger.error(f"[AIBOT_MSG] bot={bot_type} JSON decode error: {e}")
            raise HTTPException(status_code=400, detail="Invalid JSON") from e
        except Exception as e:
            logger.exception(f"[AIBOT_MSG] bot={bot_type} Error: {e}")
            raise HTTPException(status_code=500, detail=str(e)) from e


async def _handle_text_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    response_url: str | None = None,
) -> Response:
    """Handle text message: start LLM processing, return immediate 'thinking' response."""
    print(
        f"[AIBOT_TEXT_START] bot={bot_type} data_keys={list(data.keys())}", flush=True
    )
    # Cleanup old tasks on each message to prevent unbounded growth
    _cleanup_old_tasks()

    text_data = data.get("text", {})
    content = _sanitize_text(text_data.get("content", "").strip())
    content = _strip_self_mention(content, bot_type)

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))
    chat_id = _extract_chat_id(data, user_id)

    # Extract quoted message content if present
    quoted_content, quoted_msg_id = _extract_quote_content(data)
    original_content = content  # Save original user input
    quoted_filename = None

    # file_output_mode will be detected inside _call_llm_async via _handle_prompt_command
    file_output_mode = False

    if quoted_content:
        # If quoting a file, content is often the filename
        # Clean it up: remove common prefixes like "user:" or "[icon]"
        clean_name = quoted_content.strip()

        # Split by newline or colon and take the last part (often contains the filename)
        if "\n" in clean_name:
            clean_name = clean_name.split("\n")[-1].strip()
        elif ":" in clean_name:
            clean_name = clean_name.split(":")[-1].strip()

        # Remove common marks
        for mark in ["[文件]", "[图片]", "附件", "📄"]:
            clean_name = clean_name.replace(mark, "")
        clean_name = clean_name.strip()

        if "." in clean_name and len(clean_name) < 100:
            quoted_filename = clean_name
            logger.info(f"[AIBOT_QUOTE] Detected quoted filename: {quoted_filename}")

    if quoted_content:
        if original_content:
            # User has both quote and their own message
            content = (
                f"[用户引用消息: {quoted_content}]\n\n用户提问: {original_content}"
            )
        else:
            # Quote-only: user just referenced something without adding text
            content = (
                f"用户引用了以下消息并@你，请针对引用内容回复:\n\n{quoted_content}"
            )
        logger.info(f"[AIBOT_QUOTE] bot={bot_type} quoted={quoted_content[:50]!r}...")

    # Validate: reject empty content (only triggers if no quote AND no text)
    # Note: Quote-only messages bypass this check intentionally - they have content
    if not content:
        logger.warning(
            f"[AIBOT_TEXT] bot={bot_type} user={user_name} empty content, skipping"
        )
        stream_id = _generate_stream_id()
        stream_json = _make_text_stream(
            stream_id, "你好!请问有什么可以帮助你的?", finish=True
        )
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    # Extract message ID for dedup
    wecom_msg_id = _extract_msg_id(data)

    # Check for duplicate message
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(
                f"[AIBOT_DEDUP] bot={bot_type} msg_id={wecom_msg_id} "
                f"returning existing stream_id={existing_stream_id}"
            )
            stream_json = _make_text_stream(
                existing_stream_id, task["content"], task["finished"]
            )
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")

    # Extract chat ID for context isolation
    chat_id = _extract_chat_id(data, user_id)

    logger.info(
        f"[AIBOT_TEXT] bot={bot_type} user={user_name} chat={chat_id} "
        f"msg_id={wecom_msg_id} content={content[:50]!r}..."
    )

    # Generate stream ID and create task BEFORE starting LLM
    stream_id = _generate_stream_id()

    task_reply = handle_task_command(content, chat_id, user_id)
    if task_reply is None and content.strip().startswith("/task"):
        task_reply = "请输入任务内容，格式：/task <内容>"
    if task_reply:
        _stream_tasks[stream_id] = {
            "content": task_reply,
            "finished": True,
            "created_at": time.time(),
            "bot_type": bot_type,
            "user_name": user_name,
        }
        if wecom_msg_id:
            _processed_messages[wecom_msg_id] = stream_id
        stream_json = _make_text_stream(stream_id, task_reply, finish=True)
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    # Store task with initial "thinking" state
    _stream_tasks[stream_id] = {
        "content": "思考中...",
        "finished": False,
        "created_at": time.time(),
        "bot_type": bot_type,
        "user_name": user_name,
    }

    # Store message ID -> stream ID mapping for dedup
    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id

    # Start LLM call asynchronously (don't wait for it)
    if bot_type == "chatgpt" and _should_proxy_chatgpt_to_opencode():
        asyncio.create_task(
            _call_opencode_async(
                stream_id=stream_id,
                content=content,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
                wecom_msg_id=wecom_msg_id,
                quoted_content=quoted_content,
                quoted_msg_id=quoted_msg_id,
                quoted_filename=quoted_filename,
            )
        )
    else:
        asyncio.create_task(
            _call_llm_async(
                stream_id=stream_id,
                bot_type=bot_type,
                content=content,
                chat_id=chat_id,
                user_id=user_id,
                user_name=user_name,
                wecom_msg_id=wecom_msg_id,
                quoted_content=quoted_content,
                quoted_msg_id=quoted_msg_id,
                quoted_filename=quoted_filename,
                response_url=response_url,
                file_output_mode=file_output_mode,
            )
        )

    # Return immediate response with "thinking" status
    stream_json = _make_text_stream(stream_id, "思考中...", finish=False)
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)

    logger.info(
        f"[AIBOT_REPLY] bot={bot_type} stream_id={stream_id} finish=False (thinking)"
    )
    return Response(content=encrypted, media_type="text/plain")


async def _handle_stream_refresh(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
) -> Response:
    """Handle stream refresh request to get updated content."""
    stream_data = data.get("stream", {})
    stream_id = stream_data.get("id", "")

    task = _stream_tasks.get(stream_id)
    if not task:
        # Task not found - may be expired or on different worker
        logger.warning(f"[AIBOT_STREAM] bot={bot_type} stream_id={stream_id} not found")
        stream_json = _make_text_stream(
            stream_id, "任务已过期，请重新提问", finish=True
        )
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    # Return current content and status
    stream_json = _make_text_stream(stream_id, task["content"], finish=task["finished"])
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)

    logger.info(
        f"[AIBOT_STREAM] bot={bot_type} stream_id={stream_id} "
        f"finish={task['finished']} content_len={len(task['content'])}"
    )

    # Clean up finished tasks older than 5 minutes
    _cleanup_old_tasks()

    return Response(content=encrypted, media_type="text/plain")


def _cleanup_old_tasks() -> None:
    """Remove expired stream tasks and message mappings from cache."""
    current_time = time.time()

    # Clean up tasks older than 5 minutes
    expired_task_ids = [
        sid
        for sid, task in _stream_tasks.items()
        if current_time - task.get("created_at", 0) > 300
    ]
    for sid in expired_task_ids:
        del _stream_tasks[sid]

    # Clean up message mappings pointing to expired tasks
    expired_msg_ids = [
        msg_id
        for msg_id, stream_id in _processed_messages.items()
        if stream_id in expired_task_ids or stream_id not in _stream_tasks
    ]
    for msg_id in expired_msg_ids:
        del _processed_messages[msg_id]

    if expired_task_ids:
        logger.debug(f"Cleaned up {len(expired_task_ids)} expired tasks")


async def _handle_mixed_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    response_url: str | None = None,
) -> Response:
    """Handle mixed messages (image + text combination).

    Downloads and decrypts images, then sends to multimodal LLM for analysis.
    """
    wecom_msg_id = _extract_msg_id(data)
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(
                f"[AIBOT_DEDUP] bot={bot_type} msg_id={wecom_msg_id} returning existing stream_id={existing_stream_id}"
            )
            stream_json = _make_text_stream(
                existing_stream_id, task["content"], task["finished"]
            )
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")

    _cleanup_old_tasks()

    # Extract text from mixed message
    text_content = _extract_text_from_mixed(data)
    image_urls = _extract_image_urls_from_mixed(data)
    has_image = len(image_urls) > 0

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))
    chat_id = _extract_chat_id(data, user_id)

    logger.info(
        f"[AIBOT_MIXED] bot={bot_type} user={user_name} "
        f"images={len(image_urls)} text={text_content[:50]!r}..."
    )

    if not text_content and not has_image:
        logger.warning(f"[AIBOT_MIXED] bot={bot_type} no content found")
        return Response(content="success", media_type="text/plain")

    # If no image, just process as text
    if not has_image:
        modified_data = data.copy()
        modified_data["text"] = {"content": text_content}
        modified_data["msgtype"] = "text"
        return await _handle_text_message(
            bot_type, modified_data, nonce, timestamp, response_url=response_url
        )

    # Process with image - try to download and decrypt
    aes_key = _get_bot_aes_key(bot_type)
    image_base64 = None
    image_error = None
    file_url = None
    storage_key = None
    file_hash = None
    stream_id: str | None = None

    # Try the first image
    if image_urls:
        success, result = _decrypt_media(image_urls[0], aes_key)
        if success and isinstance(result, (bytes, bytearray)):
            image_bytes = bytes(result)
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            logger.info(f"[AIBOT_MIXED] bot={bot_type} image decrypted successfully")

            # Use same stream_id logic to avoid duplicate uploads
            stream_id = _generate_stream_id()
            if wecom_msg_id:
                _processed_messages[wecom_msg_id] = stream_id

            # Upload to cloud storage (UCS Phase 1) - Fix: Persistence for mixed messages
            file_url, storage_key, mime_type, filename = _upload_image_to_ucs(
                image_bytes
            )
            file_hash = schedule_file_extraction(
                chat_id=chat_id,
                wecom_msg_id=wecom_msg_id,
                storage_key=storage_key,
                filename=filename,
                mime_type=mime_type,
                file_bytes=image_bytes,
            )
        else:
            image_error = result
            logger.warning(
                f"[AIBOT_MIXED] bot={bot_type} image decrypt failed: {result}"
            )

    # Build prompt
    if text_content:
        prompt = text_content
    else:
        prompt = "请描述这张图片的内容"

    # If image decryption failed, fall back to text-only
    if not image_base64:
        error_note = f"\n\n（提示：图片处理失败：{image_error}）" if image_error else ""
        modified_data = data.copy()
        modified_data["text"] = {"content": prompt + error_note}
        modified_data["msgtype"] = "text"
        return await _handle_text_message(
            bot_type, modified_data, nonce, timestamp, response_url=response_url
        )

    # Process with image using vision API
    if stream_id is None:
        stream_id = _generate_stream_id()
    return await _handle_vision_message(
        bot_type,
        data,
        nonce,
        timestamp,
        prompt,
        image_base64,
        user_id,
        user_name,
        file_url,
        storage_key,
        stream_id,
        file_hash=file_hash,
        response_url=response_url,
    )


async def _handle_file_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    response_url: str | None = None,
) -> Response:
    """Handle file-only messages (PDF, docs, spreadsheets)."""
    wecom_msg_id = _extract_msg_id(data)
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(
                f"[AIBOT_DEDUP] bot={bot_type} file msg_id={wecom_msg_id} returning cached response"
            )
            stream_json = _make_text_stream(
                existing_stream_id, task["content"], task["finished"]
            )
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")

    _cleanup_old_tasks()

    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))
    chat_id = _extract_chat_id(data, user_id)

    file_url, file_name, mime_type = _extract_file_info(data)
    logger.info(
        f"[AIBOT_FILE] bot={bot_type} user={user_name} file={file_name} mime={mime_type} "
        f"url={(file_url[:60] + '...') if file_url else 'None'}"
    )

    if not file_url:
        return _file_error_response(
            bot_type,
            nonce,
            timestamp,
            user_id,
            user_name,
            chat_id,
            "未获取到文件链接，请重试。",
        )

    try:
        resp = requests.get(file_url, timeout=60)
        resp.raise_for_status()
        file_bytes = resp.content
    except Exception as e:
        logger.error(f"[AIBOT_FILE] Failed to download file: {e}")
        return _file_error_response(
            bot_type,
            nonce,
            timestamp,
            user_id,
            user_name,
            chat_id,
            f"文件下载失败：{str(e)[:50]}",
        )

    header_name = None
    content_disp = resp.headers.get("Content-Disposition", "")
    if "filename=" in content_disp:
        header_name = content_disp.split("filename=")[-1].strip('"')

    if not file_name or file_name in ("unnamed", "unknown"):
        file_name = header_name
    if not file_name:
        url_path = urlparse(file_url).path
        name_from_url = os.path.basename(url_path)
        file_name = name_from_url or f"file_{wecom_msg_id or int(time.time())}"

    file_name = _sanitize_filename(file_name)

    if not mime_type or mime_type == "application/octet-stream":
        header_ct = resp.headers.get("Content-Type", "")
        if header_ct:
            mime_type = header_ct.split(";")[0].strip()
    if not mime_type or mime_type == "application/octet-stream":
        guessed = mimetypes.guess_type(file_name)[0]
        if guessed:
            mime_type = guessed

    storage = get_storage_manager()
    upload_res = storage.upload_file(file_bytes, file_name, content_type=mime_type)

    file_hash = schedule_file_extraction(
        chat_id=chat_id,
        wecom_msg_id=wecom_msg_id,
        storage_key=upload_res.key,
        filename=file_name,
        mime_type=mime_type,
        file_bytes=file_bytes,
    )

    context_manager = get_context_manager()
    context_manager.save_file(
        chat_id=chat_id,
        sender_id=user_id,
        sender_name=user_name,
        file_uri=upload_res.url,
        filename=file_name,
        mime_type=mime_type,
        file_hash=file_hash,
        wecom_msg_id=wecom_msg_id,
        bot_type=bot_type,
        storage_key=upload_res.key,
    )
    context_manager.add_message(
        chat_id=chat_id,
        sender_id=user_id,
        sender_name=user_name,
        content=f"[文件: {file_name}] 已保存并上传",
        role="user",
        wecom_msg_id=wecom_msg_id,
        bot_type=bot_type,
    )

    stream_id = _generate_stream_id()
    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id

    response_text = "正在分析文件..."
    _stream_tasks[stream_id] = {
        "content": response_text,
        "finished": False,
        "created_at": time.time(),
        "bot_type": bot_type,
        "chat_id": chat_id,
        "user_id": user_id,
        "user_name": user_name,
    }

    prompt = f"用户上传了文件 {file_name}，请总结文件主要内容并回答问题。"
    asyncio.create_task(
        _call_llm_async(
            stream_id=stream_id,
            bot_type=bot_type,
            content=prompt,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            wecom_msg_id=wecom_msg_id,
            quoted_content=None,
            response_url=response_url,
        )
    )

    stream_json = _make_text_stream(stream_id, response_text, finish=False)
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
    return Response(content=encrypted, media_type="text/plain")


def _should_proxy_chatgpt_to_opencode() -> bool:
    return os.getenv("CHATGPT_PROXY_OPENCODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _strip_self_mention(content: str, bot_type: str) -> str:
    """Remove the bot's own @mention so OpenCode doesn't get confused."""
    if not content:
        return content
    # Normalize non-breaking spaces
    cleaned = content.replace("\u00a0", " ")
    pattern = rf"(?:^|\s)@{re.escape(bot_type)}\b"
    cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split())


def _should_use_opencode_stream() -> bool:
    raw = os.getenv("OPENCODE_USE_STREAM", "").strip().lower()
    if raw == "":
        return True
    return raw in {"1", "true", "yes"}


def _get_opencode_agent() -> str | None:
    raw = os.getenv("OPENCODE_AGENT", "sisyphus").strip()
    if not raw:
        return None
    if raw.lower() in {"none", "null", "off", "disabled"}:
        return None
    return raw


async def _ensure_opencode_session_idle(
    opencode_client: OpenCodeClient,
    session_id: str,
    max_wait: float = 8.0,
    poll_interval: float = 1.0,
) -> bool:
    """Abort busy sessions and reuse the same session (mirrors OpenCode UI behavior)."""
    try:
        status = opencode_client.get_session_status(session_id)
        if status.get("type") != "busy":
            return True
        logger.warning(
            f"[OPENCODE] Session {session_id} busy before prompt; aborting to avoid loops"
        )
        opencode_client.abort_session(session_id)
        deadline = time.time() + max_wait
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            status = opencode_client.get_session_status(session_id)
            if status.get("type") != "busy":
                return True
        logger.warning(
            f"[OPENCODE] Session {session_id} still busy after abort; skipping prompt"
        )
        return False
    except Exception as e:
        logger.warning(f"[OPENCODE] Failed to check/abort session {session_id}: {e}")
        return True


async def _call_opencode_async(
    stream_id: str,
    content: str,
    chat_id: str,
    user_id: str,
    user_name: str,
    wecom_msg_id: str | None,
    quoted_content: str | None,
    quoted_msg_id: str | None,
    quoted_filename: str | None,
) -> None:
    global _opencode_client
    global _opencode_session_store

    opencode_client: OpenCodeClient | None = None
    session_store: SessionStore | None = None
    run_prompt_fn = None
    repo_path = os.getenv("DEFAULT_REPO_PATH", "/opt/oh-my-opencode")
    file_output_mode = False
    link_only_mode = False
    force_abort = False
    allow_force_fallback = False

    try:
        # Handle /file-html and other prompt commands (OpenCode path).
        stripped_content = content.strip()
        if stripped_content.startswith("/"):
            cmd_parts: list[str] = stripped_content.split(maxsplit=1)
            command = cmd_parts[0].lstrip("/")
            args = cmd_parts[1] if len(cmd_parts) > 1 else ""
            cmd_result = _handle_prompt_command(
                command=command,
                args=args,
                bot_type="chatgpt",
                chat_id=chat_id,
                user_id=user_id,
            )
            if cmd_result:
                if cmd_result.get("continue_with_llm"):
                    file_output_mode = bool(cmd_result.get("file_output_mode", False))
                    if file_output_mode:
                        link_only_mode = True
                    content = cmd_result.get("user_request", content)
                    force_abort = bool(cmd_result.get("force_abort", False))
                    allow_force_fallback = force_abort
                else:
                    _stream_tasks[stream_id]["content"] = cmd_result.get(
                        "content", "Command handled."
                    )
                    _stream_tasks[stream_id]["finished"] = True
                    return

            # If /force wraps another command, re-process it now (e.g., /force /file-html ...).
            if content.strip().startswith("/"):
                nested_parts: list[str] = content.strip().split(maxsplit=1)
                nested_command = nested_parts[0].lstrip("/")
                nested_args = nested_parts[1] if len(nested_parts) > 1 else ""
                nested_result = _handle_prompt_command(
                    command=nested_command,
                    args=nested_args,
                    bot_type="chatgpt",
                    chat_id=chat_id,
                    user_id=user_id,
                )
                if nested_result:
                    if nested_result.get("continue_with_llm"):
                        file_output_mode = bool(
                            nested_result.get("file_output_mode", False)
                        )
                        if file_output_mode:
                            link_only_mode = True
                        content = nested_result.get("user_request", content)
                    else:
                        _stream_tasks[stream_id]["content"] = nested_result.get(
                            "content", "Command handled."
                        )
                        _stream_tasks[stream_id]["finished"] = True
                        return

        opencode_url = os.getenv("OPENCODE_URL", "http://127.0.0.1:4096")
        opencode_api_key = os.getenv("OPENCODE_API_KEY")
        state_dir = os.path.dirname(
            os.getenv("HISTORY_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
        )
        session_file = os.path.join(state_dir, "opencode_sessions.json")

        if _opencode_client is None:
            _opencode_client = OpenCodeClient(opencode_url, api_key=opencode_api_key)
        if _opencode_session_store is None:
            _opencode_session_store = SessionStore(session_file)

        opencode_client = _opencode_client
        session_store = _opencode_session_store
        if opencode_client is None or session_store is None:
            raise RuntimeError("OpenCode client initialization failed")

        safe_content = content.strip() if content else ""
        if not safe_content:
            safe_content = "(empty message)"

        lang_guard = (
            "IMPORTANT: Reply in Chinese. Technical terms that are commonly written in English "
            "may remain in English. The only exception is a leading line like "
            "'Using skill: save-to-workdir', which may remain in English."
        )
        parts: list[dict[str, Any]] = [
            {"type": "text", "text": lang_guard + "\n\n" + safe_content}
        ]
        if quoted_content:
            parts.append(
                {
                    "type": "text",
                    "text": f"[Quoted] {quoted_content}",
                    "metadata": {"quoted_msg_id": quoted_msg_id},
                }
            )
        if quoted_filename:
            parts.append(
                {
                    "type": "text",
                    "text": f"[Quoted File] {quoted_filename}",
                }
            )

        # Let OpenCode generate message IDs to preserve ordering (avoids loop exits).
        message_id: str | None = None

        def run_prompt(session_uuid: str) -> str:
            result_text = ""
            logger.info(f"[OPENCODE] Starting prompt for session={session_uuid}")
            opencode_agent = _get_opencode_agent()
            try:
                config = opencode_client.get_config()
                agent_cfg = config.get("agent", {}) if isinstance(config, dict) else {}
                agent_info = agent_cfg.get(opencode_agent or "", {})
                model_info = (
                    agent_info.get("model") if isinstance(agent_info, dict) else None
                )
                logger.info(
                    "[OPENCODE] Using agent=%s model=%s",
                    opencode_agent,
                    model_info,
                )
            except Exception as e:
                logger.warning(f"[OPENCODE] Failed to read config for model: {e}")
            parent_id: str | None = None
            try:
                existing = opencode_client.get_session_messages(session_uuid)
                for msg in reversed(existing):
                    info = msg.get("info", {}) if isinstance(msg, dict) else {}
                    if info.get("role") == "assistant":
                        parent_id = info.get("id")
                        break
                if parent_id:
                    logger.info(
                        f"[OPENCODE] Using parentID={parent_id} for session={session_uuid}"
                    )
            except Exception as e:
                logger.warning(f"[OPENCODE] Failed to resolve parentID: {e}")

            # Try polling-based approach (handles OpenCode's agentic loops)
            try:
                logger.info(f"[OPENCODE] Using polling approach")
                for event in opencode_client.prompt_interactive_with_polling(
                    session_id=session_uuid,
                    parts=parts,
                    message_id=message_id,
                    directory=repo_path,
                    agent=opencode_agent,
                    parent_id=parent_id,
                    poll_interval=3.0,
                    max_wait=180.0,  # 3 minutes max
                ):
                    event_type = event.get("type", "")
                    logger.info(f"[OPENCODE] Got event type={event_type}")
                    if event_type in ("text", "final"):
                        text = event.get("text", "")
                        if text:
                            result_text = text
                            _stream_tasks[stream_id]["content"] = result_text
                            logger.info(
                                f"[OPENCODE] Got text response: {text[:100]}..."
                            )
                    elif event_type == "complete":
                        # Got immediate response
                        data = event.get("data", {})
                        result_text = _extract_opencode_text(data)
                        if result_text:
                            _stream_tasks[stream_id]["content"] = result_text
                            logger.info(
                                f"[OPENCODE] Got complete response: {result_text[:100]}..."
                            )
                    elif event_type == "error":
                        result_text = event.get(
                            "message", "OpenCode returned an error."
                        )
                        _stream_tasks[stream_id]["content"] = result_text
                        logger.warning(f"[OPENCODE] {result_text}")
                        break

                if result_text:
                    logger.info(
                        f"[OPENCODE] Polling succeeded with {len(result_text)} chars"
                    )
                    return result_text
                else:
                    logger.warning(f"[OPENCODE] Polling returned no result")
            except requests.HTTPError as e:
                logger.error(f"[OPENCODE] HTTP error in polling: {e}")
                raise
            except Exception as e:
                logger.warning(f"[OPENCODE] Polling failed: {e}", exc_info=True)

            # Fallback to streaming if polling didn't work
            if _should_use_opencode_stream():
                try:
                    logger.info(f"[OPENCODE] Trying streaming fallback")
                    for event in opencode_client.stream_interactive(
                        session_id=session_uuid,
                        parts=parts,
                        message_id=message_id,
                        directory=repo_path,
                        agent=opencode_agent,
                        parent_id=parent_id,
                    ):
                        delta = _extract_opencode_stream_text(event)
                        if not delta:
                            continue
                        if len(delta) > len(result_text) and delta.startswith(
                            result_text
                        ):
                            result_text = delta
                        else:
                            result_text += delta
                        _stream_tasks[stream_id]["content"] = result_text
                except requests.HTTPError:
                    raise
                except Exception as e:
                    logger.warning(f"[OPENCODE] Stream failed: {e}")

            # Final fallback to synchronous call with long timeout
            if not result_text:
                logger.info(f"[OPENCODE] Trying synchronous fallback")
                response = opencode_client.prompt_interactive(
                    session_id=session_uuid,
                    parts=parts,
                    message_id=message_id,
                    directory=repo_path,
                    agent=opencode_agent,
                    parent_id=parent_id,
                )
                if response is not None:
                    try:
                        data = response.json()
                        result_text = _extract_opencode_text(data)
                        logger.info(f"[OPENCODE] Sync got {len(result_text)} chars")
                    except ValueError:
                        result_text = response.text.strip()

            return result_text

        run_prompt_fn = run_prompt

        session_id = session_store.get_session_id(
            chat_id,
            creator=lambda: opencode_client.create_session(directory=repo_path),
        )
        # If force-abort requested, cancel any running work immediately.
        if force_abort:
            logger.warning(
                f"[OPENCODE] Force abort requested; aborting session {session_id}"
            )
            opencode_client.abort_session(session_id)
        # If session is busy, abort and reuse same session (UI behavior).
        ready = await _ensure_opencode_session_idle(opencode_client, session_id)
        if not ready:
            if allow_force_fallback:
                logger.warning(
                    f"[OPENCODE] Force fallback: creating new session for chat={chat_id}"
                )
                session_id = opencode_client.create_session(directory=repo_path)
                session_store.set_session_id(chat_id, session_id)
            else:
                _stream_tasks[stream_id]["content"] = (
                    "OpenCode session is still busy after abort. Please retry in a few seconds."
                )
                _stream_tasks[stream_id]["finished"] = True
                return

        request_start_ms = int(time.time() * 1000)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_prompt, session_id)
        if not result:
            result = "OpenCode returned an empty response."

        if file_output_mode:
            # For file-html, wait for session idle (or timeout) before selecting the final content.
            try:
                deadline = time.time() + 280.0
                while time.time() < deadline:
                    status = opencode_client.get_session_status(session_id)
                    if status.get("type") != "busy":
                        break
                    time.sleep(2.0)
            except Exception as e:
                logger.warning(
                    f"[OPENCODE] Failed while waiting for idle before file-html: {e}"
                )
            # For file-html, ensure we use the longest assistant text for this turn (not a lead-in snippet).
            try:
                messages = opencode_client.get_session_messages(session_id)
                best_text = result
                # Find the user message that matches this request (by time + content).
                selected_user_id = None
                best_score = -1
                for msg in messages:
                    info = msg.get("info", {})
                    if info.get("role") != "user":
                        continue
                    ts = info.get("time", {}).get("created", 0) or 0
                    if ts < request_start_ms - 2000:
                        continue
                    content_text = ""
                    for part in msg.get("parts", []):
                        if part.get("type") == "text":
                            content_text = part.get("text", "")
                            break
                    score = 0
                    if content_text and content.strip():
                        if content_text.strip() == content.strip():
                            score += 3
                        elif (
                            content.strip()[:50]
                            and content.strip()[:50] in content_text
                        ):
                            score += 2
                    if ts >= request_start_ms - 2000:
                        score += 1
                    if score > best_score:
                        best_score = score
                        selected_user_id = info.get("id")

                if selected_user_id:
                    for msg in messages:
                        info = msg.get("info", {})
                        if info.get("role") != "assistant":
                            continue
                        parent_id = info.get("parentID") or info.get("parentId")
                        if parent_id != selected_user_id:
                            continue
                        for part in msg.get("parts", []):
                            if part.get("type") == "text":
                                text = part.get("text", "")
                                if isinstance(text, str) and len(text) > len(best_text):
                                    best_text = text
                if best_text != result:
                    logger.info(
                        "[OPENCODE] Using longest assistant text for file-html output"
                    )
                    result = best_text
            except Exception as e:
                logger.warning(
                    f"[OPENCODE] Failed to select longest text before file-html: {e}"
                )
            result = await _process_llm_file_output(
                bot_type="chatgpt",
                chat_id=chat_id,
                content=result,
                user_id=user_id,
                user_name=user_name,
                file_only_mode=True,
                is_report_request=False,
                template_name=None,
            )
            if link_only_mode:
                import re

                match = re.search(r"https?://\\S+", result)
                if match:
                    result = match.group(0)

        _stream_tasks[stream_id]["content"] = result
        _stream_tasks[stream_id]["finished"] = True
    except requests.HTTPError as e:
        resp = e.response
        detail = resp.text if resp is not None else str(e)
        if _is_opencode_not_found(resp, detail):
            try:
                if not opencode_client or not session_store or not run_prompt_fn:
                    raise RuntimeError("OpenCode client not initialized")

                new_session_id = opencode_client.create_session(directory=repo_path)
                session_store.set_session_id(chat_id, new_session_id)
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, run_prompt_fn, new_session_id)
                if not result:
                    result = "OpenCode returned an empty response."

                _stream_tasks[stream_id]["content"] = result
                _stream_tasks[stream_id]["finished"] = True
                return
            except Exception as retry_error:
                detail = str(retry_error)

        _stream_tasks[stream_id]["content"] = f"抱歉,OpenCode服务暂时不可用: {detail}"
        _stream_tasks[stream_id]["finished"] = True
    except Exception as e:
        _stream_tasks[stream_id]["content"] = f"抱歉,OpenCode服务暂时不可用: {e}"
        _stream_tasks[stream_id]["finished"] = True


def _extract_opencode_text(data: dict) -> str:
    if not isinstance(data, dict):
        return ""

    direct = data.get("content") or data.get("message")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts = data.get("parts")
    if isinstance(parts, list):
        texts = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("text", "reasoning"):
                if part.get("ignored"):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        if texts:
            return "\n".join(texts)

    info = data.get("info")
    if isinstance(info, dict):
        error = info.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()

    return ""


def _extract_opencode_stream_text(event: Any) -> str:
    if not isinstance(event, dict):
        return ""

    event_type = event.get("type")
    if event_type == "error":
        error = event.get("content") or event.get("message") or event.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()

    for key in ("delta", "content", "text", "message"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value

    if "parts" in event:
        return _extract_opencode_text(event)

    return ""


def _is_opencode_not_found(resp: requests.Response | None, detail: str) -> bool:
    if resp is not None and resp.status_code == 404:
        return True
    if detail:
        return "NotFoundError" in detail or "Resource not found" in detail
    return False


def _file_error_response(
    bot_type: str,
    nonce: str,
    timestamp: str,
    user_id: str,
    user_name: str,
    chat_id: str,
    message: str,
) -> Response:
    stream_id = _generate_stream_id()
    _stream_tasks[stream_id] = {
        "content": message,
        "finished": True,
        "created_at": time.time(),
        "completed_at": time.time(),
        "bot_type": bot_type,
        "chat_id": chat_id,
        "user_id": user_id,
        "user_name": user_name,
    }
    stream_json = _make_text_stream(stream_id, message, finish=True)
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
    return Response(content=encrypted, media_type="text/plain")


async def _handle_image_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    response_url: str | None = None,
) -> Response:
    """Handle image-only messages.

    Downloads and decrypts the image, then sends to multimodal LLM for analysis.
    """
    wecom_msg_id = _extract_msg_id(data)
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(
                f"[AIBOT_DEDUP] bot={bot_type} image msg_id={wecom_msg_id} returning cached response"
            )
            stream_json = _make_text_stream(
                existing_stream_id, task["content"], task["finished"]
            )
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")

    _cleanup_old_tasks()

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))

    logger.info(f"[AIBOT_IMAGE] bot={bot_type} user={user_name} received image")

    # Extract image URL
    image_urls = _extract_image_urls_from_mixed(data)
    if not image_urls:
        logger.warning(f"[AIBOT_IMAGE] bot={bot_type} no image URL found")
        stream_id = _generate_stream_id()
        response_text = "收到你的消息，但未找到图片内容。请重新发送图片。"
        _stream_tasks[stream_id] = {
            "content": response_text,
            "finished": True,
            "created_at": time.time(),
            "completed_at": time.time(),
            "bot_type": bot_type,
            "chat_id": _extract_chat_id(data, user_id),
            "user_id": user_id,
            "user_name": user_name,
        }
        stream_json = _make_text_stream(stream_id, response_text, finish=True)
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    # Try to download and decrypt image
    aes_key = _get_bot_aes_key(bot_type)
    success, result = _decrypt_media(image_urls[0], aes_key)

    if not success:
        logger.error(f"[AIBOT_IMAGE] bot={bot_type} decrypt failed: {result}")
        stream_id = _generate_stream_id()
        response_text = (
            f"收到你的图片，但处理时出现问题：{result}\n\n请稍后重试，或添加文字说明。"
        )
        _stream_tasks[stream_id] = {
            "content": response_text,
            "finished": True,
            "created_at": time.time(),
            "completed_at": time.time(),
            "bot_type": bot_type,
            "chat_id": _extract_chat_id(data, user_id),
            "user_id": user_id,
            "user_name": user_name,
        }
        stream_json = _make_text_stream(stream_id, response_text, finish=True)
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    if not isinstance(result, (bytes, bytearray)):
        logger.error(f"[AIBOT_IMAGE] bot={bot_type} decrypt returned non-bytes")
        stream_id = _generate_stream_id()
        response_text = "收到你的图片，但处理时出现问题，请稍后重试。"
        _stream_tasks[stream_id] = {
            "content": response_text,
            "finished": True,
            "created_at": time.time(),
            "completed_at": time.time(),
            "bot_type": bot_type,
            "chat_id": _extract_chat_id(data, user_id),
            "user_id": user_id,
            "user_name": user_name,
        }
        stream_json = _make_text_stream(stream_id, response_text, finish=True)
        encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
        return Response(content=encrypted, media_type="text/plain")

    # Image decrypted successfully
    image_bytes = bytes(result)
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = "请描述并分析这张图片的内容"
    # Use same stream_id logic to avoid duplicate uploads
    stream_id = _generate_stream_id()
    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id

    # Upload to cloud storage (UCS Phase 1)
    file_url, storage_key, mime_type, filename = _upload_image_to_ucs(image_bytes)
    file_hash = schedule_file_extraction(
        chat_id=_extract_chat_id(data, user_id),
        wecom_msg_id=wecom_msg_id,
        storage_key=storage_key,
        filename=filename,
        mime_type=mime_type,
        file_bytes=image_bytes,
    )

    logger.info(f"[AIBOT_IMAGE] bot={bot_type} image ready, sending to vision API")

    return await _handle_vision_message(
        bot_type,
        data,
        nonce,
        timestamp,
        prompt,
        image_base64,
        user_id,
        user_name,
        file_url,
        storage_key,
        stream_id,
        file_hash=file_hash,
        response_url=response_url,
    )


async def _handle_vision_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    prompt: str,
    image_base64: str,
    user_id: str,
    user_name: str,
    file_url: str | None = None,
    storage_key: str | None = None,
    existing_stream_id: str | None = None,
    file_hash: str | None = None,
    response_url: str | None = None,
) -> Response:
    """Handle vision (image+text) message with multimodal LLM.

    This is the core function that calls the vision API asynchronously.
    """
    config = BOT_CONFIGS[bot_type]
    provider = config["provider"] if isinstance(config["provider"], str) else ""
    system_prompt = (
        config["system_prompt"] if isinstance(config["system_prompt"], str) else ""
    )

    chat_id = _extract_chat_id(data, user_id)
    wecom_msg_id = _extract_msg_id(data)
    _, quoted_msg_id = _extract_quote_content(data)

    # Check for duplicate message
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(
                f"[AIBOT_VISION] Returning cached response for msgid={wecom_msg_id}"
            )
            stream_json = _make_text_stream(
                existing_stream_id, task["content"], task["finished"]
            )
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")

    # Create stream task for tracking
    stream_id = existing_stream_id or _generate_stream_id()
    _stream_tasks[stream_id] = {
        "content": "正在分析图片...",
        "finished": False,
        "created_at": time.time(),
        "bot_type": bot_type,
        "chat_id": chat_id,
        "user_id": user_id,
        "user_name": user_name,
    }

    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id

    is_report_request = False  # Initialize for scope safety

    # Save persistent context (UCS Phase 1)
    if file_url:
        try:
            # Fix: Use correct metadata for persistent context
            mime_type = "image/jpeg"
            filename = "image.jpg"
            if ".png" in file_url:
                mime_type = "image/png"
                filename = "image.png"
            elif ".gif" in file_url:
                mime_type = "image/gif"
                filename = "image.gif"
            elif ".bmp" in file_url:
                mime_type = "image/bmp"
                filename = "image.bmp"

            # Detect report intent for vision flow
            is_report_request = _detect_daily_report_intent(prompt)

            # Fix: Use a derived message ID for the file context to avoid conflict with the user message (persistence dedup)
            file_msg_id = f"file_{wecom_msg_id}" if wecom_msg_id else None
            get_context_manager().save_file(
                chat_id=chat_id,
                sender_id=user_id,
                sender_name=user_name,
                file_uri=file_url,
                filename=filename,
                mime_type=mime_type,
                file_hash=file_hash,
                wecom_msg_id=file_msg_id,
                bot_type=bot_type,
                storage_key=storage_key,
            )
            logger.info(
                f"[AIBOT_VISION] Saved persistent image context for chat={chat_id} (msgid={file_msg_id})"
            )
        except Exception as e:
            logger.error(f"[AIBOT_VISION] Failed to save image context: {e}")

    # Start vision LLM call asynchronously
    asyncio.create_task(
        _call_vision_llm_async(
            stream_id=stream_id,
            bot_type=bot_type,
            provider=provider,
            prompt=prompt,
            image_base64=image_base64,
            system_prompt=system_prompt,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            wecom_msg_id=wecom_msg_id,
            quoted_msg_id=quoted_msg_id,
            response_url=response_url,
            is_report_request=is_report_request,
        )
    )

    # Return immediate "analyzing" response
    stream_json = _make_text_stream(stream_id, "正在分析图片...", finish=False)
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)

    logger.info(f"[AIBOT_VISION] bot={bot_type} stream_id={stream_id} analyzing image")
    return Response(content=encrypted, media_type="text/plain")
