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
            return decrypted_echostr

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

            data = json.loads(decrypted_msg)
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

    # Try the first image
    if image_urls:
        success, result = _decrypt_media(image_urls[0], aes_key)
        if success:
            image_base64 = base64.b64encode(result).decode("utf-8")
            logger.info(f"[AIBOT_MIXED] bot={bot_type} image decrypted successfully")

            # Use same stream_id logic to avoid duplicate uploads
            stream_id = _generate_stream_id()
            if wecom_msg_id:
                _processed_messages[wecom_msg_id] = stream_id

            # Upload to cloud storage (UCS Phase 1) - Fix: Persistence for mixed messages
            file_url, storage_key, mime_type, filename = _upload_image_to_ucs(result)
            file_hash = schedule_file_extraction(
                chat_id=chat_id,
                wecom_msg_id=wecom_msg_id,
                storage_key=storage_key,
                filename=filename,
                mime_type=mime_type,
                file_bytes=result,
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

    try:
        opencode_url = os.getenv("OPENCODE_URL", "http://127.0.0.1:4096")
        repo_path = os.getenv("DEFAULT_REPO_PATH", "/opt/oh-my-opencode")
        state_dir = os.path.dirname(
            os.getenv("HISTORY_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
        )
        session_file = os.path.join(state_dir, "opencode_sessions.json")

        if _opencode_client is None:
            _opencode_client = OpenCodeClient(opencode_url)
        if _opencode_session_store is None:
            _opencode_session_store = SessionStore(session_file)

        session_id = _opencode_session_store.get_session_id(
            chat_id,
            creator=lambda: _opencode_client.create_session(directory=repo_path),
        )

        safe_content = content.strip() if content else ""
        if not safe_content:
            safe_content = "(empty message)"

        parts = [{"type": "text", "text": safe_content}]
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

        raw_message_id = wecom_msg_id or stream_id
        message_id = raw_message_id
        if not message_id.startswith("msg"):
            message_id = f"msg_{message_id}"

        response = _opencode_client.prompt_interactive(
            session_id=session_id,
            parts=parts,
            message_id=message_id,
            directory=repo_path,
        )
        result = ""
        if response is not None:
            try:
                data = response.json()
                result = _extract_opencode_text(data)
            except ValueError:
                result = response.text.strip()
        if not result:
            result = "OpenCode returned an empty response."

        _stream_tasks[stream_id]["content"] = result
        _stream_tasks[stream_id]["finished"] = True
    except requests.HTTPError as e:
        resp = e.response
        detail = resp.text if resp is not None else str(e)
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

    # Image decrypted successfully
    image_base64 = base64.b64encode(result).decode("utf-8")
    prompt = "请描述并分析这张图片的内容"
    # Use same stream_id logic to avoid duplicate uploads
    stream_id = _generate_stream_id()
    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id

    # Upload to cloud storage (UCS Phase 1)
    file_url, storage_key, mime_type, filename = _upload_image_to_ucs(result)
    file_hash = schedule_file_extraction(
        chat_id=_extract_chat_id(data, user_id),
        wecom_msg_id=wecom_msg_id,
        storage_key=storage_key,
        filename=filename,
        mime_type=mime_type,
        file_bytes=result,
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
    provider = config["provider"]
    system_prompt = config["system_prompt"]

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
