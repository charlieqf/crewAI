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
import time
from typing import Any

import requests
import urllib3
from Crypto.Cipher import AES
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from src.crewai_enterprise.utils.wecom_json_crypto import WXBizJsonMsgCrypt
from src.crewai_enterprise.utils.llm_router import LLMError, get_router
from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.storage_manager import get_storage_manager


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================================
# WARNING: In-memory caches - NOT suitable for multi-worker/multi-instance!
# For production with multiple Uvicorn workers or load-balanced instances,
# replace these with Redis or a shared database.
# ============================================================================
# Global storage for streaming tasks and processed messages
# In production, use Redis instead of memory
_stream_tasks: dict[str, dict[str, Any]] = {}
_processed_messages: dict[str, str] = {}  # msgid -> stream_id (dedup)


# Bot configurations
# EncodingAESKey and Token must match WeCom admin console
BOT_CONFIGS: dict[str, dict[str, str]] = {
    "gemini": {
        "provider": "gemini",
        "token_env": "GEMINI_BOT_TOKEN",
        "aes_key_env": "GEMINI_BOT_ENCODING_AES_KEY",
        "system_prompt": "你是Gemini,一个擅长长文本分析和理解的AI助手。请用中文回答。\n\n重要提示：如果用户要求生成文件(如HTML报告、代码文件、PDF等),你必须严格按照以下格式输出:\n\n<FILE name=\"文件名.扩展名\">文件的完整内容</FILE>\n\n例如,如果生成HTML报告:\n<FILE name=\"分析报告.html\">\n<!DOCTYPE html>\n<html>...(完整HTML内容)...</html>\n</FILE>\n\n系统会自动提取该标签内的内容,保存为文件并发送给用户。请确保文件内容完整,并放在<FILE>标签内。",
    },
    "chatgpt": {
        "provider": "openai",
        "token_env": "CHATGPT_BOT_TOKEN",
        "aes_key_env": "CHATGPT_BOT_ENCODING_AES_KEY",
        "system_prompt": "你是ChatGPT,一个友好的AI助手。请用简洁清晰的中文回答问题。",
    },
    "grok": {
        "provider": "xai",
        "token_env": "GROK_BOT_TOKEN",
        "aes_key_env": "GROK_BOT_ENCODING_AES_KEY",
        "system_prompt": "你是Grok,一个风趣幽默且知识渊博的AI助手。请用中文回答。",
    },
}


def _generate_stream_id() -> str:
    """Generate a unique stream ID for task tracking."""
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _get_bot_crypto(bot_type: str) -> WXBizJsonMsgCrypt:
    """Get WXBizJsonMsgCrypt instance for a specific bot."""
    config = BOT_CONFIGS.get(bot_type)
    if not config:
        raise ValueError(f"Unknown bot type: {bot_type}")

    token = os.getenv(config["token_env"], "")
    aes_key = os.getenv(config["aes_key_env"], "")

    if not token or not aes_key:
        raise ValueError(
            f"Missing configuration for {bot_type}: "
            f"set {config['token_env']} and {config['aes_key_env']}"
        )

    # For intelligent robots, receiveid is empty string
    return WXBizJsonMsgCrypt(token, aes_key, "")


def _get_bot_aes_key(bot_type: str) -> str:
    """Get the EncodingAESKey for a specific bot."""
    config = BOT_CONFIGS.get(bot_type)
    if not config:
        raise ValueError(f"Unknown bot type: {bot_type}")
    return os.getenv(config["aes_key_env"], "")


def _decrypt_media(media_url: str, aes_key_base64: str) -> tuple[bool, bytes | str]:
    """Download and decrypt encrypted media (image/file) from WeCom.

    Args:
        media_url: URL of the encrypted media
        aes_key_base64: Base64-encoded AES key (same as EncodingAESKey)

    Returns:
        tuple: (success, data) - if success, data is decrypted bytes; otherwise error message
    """
    try:
        # 1. Download encrypted media
        logger.info(f"[MEDIA] Downloading encrypted media: {media_url[:80]}...")
        response = requests.get(media_url, timeout=60)  # Increase timeout for files
        response.raise_for_status()
        encrypted_data = response.content
        logger.info(f"[MEDIA] Downloaded {len(encrypted_data)} bytes")

        # 2. Prepare AES key and IV
        if not aes_key_base64:
            raise ValueError("AES key is empty")

        # Base64 decode key (handle padding)
        aes_key = base64.b64decode(aes_key_base64 + "=" * (-len(aes_key_base64) % 4))
        if len(aes_key) != 32:
            raise ValueError(f"Invalid AES key length: expected 32, got {len(aes_key)}")

        iv = aes_key[:16]  # IV is first 16 bytes of key

        # 3. Decrypt data
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted_data = cipher.decrypt(encrypted_data)

        # 4. Remove PKCS#7 padding
        pad_len = decrypted_data[-1]
        if pad_len > 32:  # AES-256 block size
            raise ValueError(f"Invalid padding length: {pad_len}")

        decrypted_data = decrypted_data[:-pad_len]
        logger.info(f"[MEDIA] Decrypted to {len(decrypted_data)} bytes")

        return True, decrypted_data

    except requests.exceptions.RequestException as e:
        error_msg = f"Media download failed: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg

    except ValueError as e:
        error_msg = f"Decryption error: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg

    except Exception as e:
        error_msg = f"Media processing error: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg


def _make_text_stream(stream_id: str, content: str, finish: bool) -> str:
    """Create a text stream response message."""
    return json.dumps(
        {
            "msgtype": "stream",
            "stream": {"id": stream_id, "finish": finish, "content": content},
        },
        ensure_ascii=False,
    )


def _encrypt_response(
    bot_type: str, stream_json: str, nonce: str, timestamp: str
) -> str:
    """Encrypt response message for WeCom."""
    crypto = _get_bot_crypto(bot_type)
    ret, encrypted = crypto.EncryptMsg(stream_json, nonce, timestamp)
    if ret != 0:
        raise ValueError(f"Encryption failed with error code: {ret}")
    return encrypted


def _extract_msg_id(data: dict) -> str | None:
    """Extract message ID from WeCom payload for dedup.

    The intelligent bot payload may use different keys.
    Try common variations including nested objects.
    """
    # Try top-level keys first
    for key in ["msgid", "msg_id", "MsgId", "message_id"]:
        if key in data:
            return str(data[key])
            
    # Fallback to nested msg object
    if "msg" in data and isinstance(data["msg"], dict):
        return data["msg"].get("msgid")

    # Check nested structures - msgid often inside text, image, etc.
    for nested_key in ["text", "image", "voice", "file", "link"]:
        if nested_key in data and isinstance(data[nested_key], dict):
            nested = data[nested_key]
            for key in ["msgid", "msg_id", "MsgId"]:
                if key in nested:
                    return str(nested[key])

    # Log available keys for debugging (helps identify correct field names)
    # Include nested structure hint for better debugging
    nested_info = {
        k: list(v.keys())[:5] if isinstance(v, dict) else type(v).__name__
        for k, v in list(data.items())[:8]
    }
    logger.debug(f"[AIBOT_MSGID] Could not extract msgid, structure: {nested_info}")
    return None


def _extract_chat_id(data: dict, user_id: str) -> str:
    """Extract chat/group ID from WeCom payload.

    The intelligent bot payload may have different structures.
    Try common variations and fall back to user_id for 1-on-1 chats.
    """
    # Try various possible key names for group chat ID
    for key in ["chat_id", "chatid", "ChatId", "roomid", "room_id", "groupid"]:
        if key in data and data[key]:
            return str(data[key])

    # Check nested structures
    if "chat" in data and isinstance(data["chat"], dict):
        chat_data = data["chat"]
        for key in ["id", "chat_id", "chatid"]:
            if key in chat_data and chat_data[key]:
                return str(chat_data[key])

    # Fall back to user_id for 1-on-1 chats
    return user_id


def _extract_quote_content(data: dict) -> tuple[str | None, str | None]:
    """Extract quoted message content and ID from WeCom payload.

    Returns:
        tuple: (content, msgid)

    WeCom intelligent bot payloads may include quoted/referenced messages.
    Common structures include:
    - data["quote"]["content"] - direct quote object
    - data["text"]["quote"] - nested in text object
    - data["reference"] - alternative naming
    """
    # Try top-level quote field
    if "quote" in data and isinstance(data["quote"], dict):
        quote_data = data["quote"]
        # Try different content field names
        msgid = quote_data.get("msgid") or quote_data.get("msg_id") or quote_data.get("MsgId")
        for key in ["content", "text", "Content", "Text"]:
            if key in quote_data and quote_data[key]:
                return str(quote_data[key]).strip(), msgid
        # If quote has type info, try to extract based on type
        if "msgtype" in quote_data:
            msgtype = quote_data["msgtype"]
            if msgtype == "text" and "text" in quote_data:
                text_obj = quote_data["text"]
                if isinstance(text_obj, dict) and "content" in text_obj:
                    msgid = quote_data.get("msgid") or quote_data.get("msg_id") or quote_data.get("MsgId")
                    return str(text_obj["content"]).strip(), msgid

    # Try quote nested in text object
    text_data = data.get("text", {})
    if isinstance(text_data, dict) and "quote" in text_data:
        quote_in_text = text_data["quote"]
        if isinstance(quote_in_text, dict):
            msgid = quote_in_text.get("msgid") or quote_in_text.get("msg_id") or quote_in_text.get("MsgId")
            for key in ["content", "text"]:
                if key in quote_in_text and quote_in_text[key]:
                    return str(quote_in_text[key]).strip(), msgid
        elif isinstance(quote_in_text, str):
            return quote_in_text.strip(), None

    # Try reference field (alternative naming)
    for ref_key in ["reference", "ref", "reply_to"]:
        if ref_key in data and isinstance(data[ref_key], dict):
            ref_data = data[ref_key]
            msgid = ref_data.get("msgid") or ref_data.get("msg_id") or ref_data.get("MsgId")
            for key in ["content", "text", "message"]:
                if key in ref_data and ref_data[key]:
                    return str(ref_data[key]).strip(), msgid

    # Log structure if we suspect there might be a quote but couldn't extract
    # Only check top-level keys to avoid performance issues with large payloads
    quote_related_keys = ["quote", "reference", "ref", "reply_to", "reply"]
    if any(k in data for k in quote_related_keys):
        logger.debug(
            f"[AIBOT_QUOTE] Possible quote detected but not extracted, "
            f"keys: {list(data.keys())[:10]}"
        )

    return None, None


async def _process_llm_file_output(
    bot_type: str,
    chat_id: str,
    content: str,
    user_id: str | None = None,
    user_name: str | None = None,
    response_url: str | None = None,
) -> str:
    """Detect and process <FILE> tags in LLM output."""
    import re
    from src.crewai_enterprise.utils.file_storage import get_file_manager
    from src.crewai_enterprise.utils.storage_manager import get_storage_manager
    from src.crewai_enterprise.utils.chat_context import get_context_manager
    
    # Pattern to match <FILE name="filename">content</FILE>
    # Use re.DOTALL to match across newlines
    file_pattern = re.compile(r'<FILE\s+name="([^"]+)">([\s\S]*?)<\/FILE>', re.IGNORECASE)
    
    matches = file_pattern.findall(content)
    if not matches:
        return content
        
    cleaned_content = content
    file_manager = get_file_manager()
    storage = get_storage_manager()
    context_manager = get_context_manager()
    
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename to prevent path traversal and remove weird characters."""
        import os
        # Only take the basename to prevent path traversal
        name = os.path.basename(name)
        # Remove any non-alphanumeric/dot/hyphen/underscore characters
        import re
        name = re.sub(r'[^\w\.\-\u4e00-\u9fa5]', '_', name)
        # Limit length
        if len(name) > 100:
            name = name[:90] + "_" + name[-9:]
        return name

    for original_filename, file_content in matches:
        try:
            filename = _sanitize_filename(original_filename)
            logger.info(f"[AIBOT_FILE] Processing generated file: {filename} (original: {original_filename}, {len(file_content)} chars)")
            
            # 1. Save to local storage
            file_info = file_manager.save_file_from_bytes(
                chat_id=chat_id,
                content=file_content.encode("utf-8"),
                filename=filename
            )
            
            # 2. Upload to Qiniu (UCS)
            cloud_url = None
            cloud_key = None
            try:
                mime_type = "text/html" if filename.endswith(".html") else "text/plain"
                upload_res = storage.upload_file(
                    data=file_content.encode("utf-8"),
                    filename=filename,
                    content_type=mime_type
                )
                cloud_url = upload_res.url
                cloud_key = upload_res.key
                # For public bucket, use direct URL (no signature needed)
                qiniu_url_display = cloud_url
                logger.info(f"[AIBOT_FILE] Uploaded to Qiniu: {cloud_url}")
            except Exception as qiniu_err:
                logger.error(f"[AIBOT_FILE] Qiniu upload failed: {qiniu_err}")
                qiniu_url_display = "(上传云端失败)"

            # 3. Save to conversation context (Auditor Refinement)
            try:
                # Use file:// prefix for local paths to ensure context manager compatibility
                final_file_uri = cloud_url or f"file://{file_info.file_path}"
                context_manager.save_file(
                    chat_id=chat_id,
                    sender_id=f"bot_{bot_type}",
                    sender_name=bot_type,
                    file_uri=final_file_uri,
                    filename=filename,
                    mime_type="text/html" if filename.endswith(".html") else "text/plain",
                    bot_type=bot_type,
                    storage_key=cloud_key
                )
                logger.info(f"[AIBOT_FILE] Saved generated file to context: {filename}")
            except Exception as ctx_err:
                logger.error(f"[AIBOT_FILE] Failed to save to context: {ctx_err}")
            
            # Note: WeCom intelligent robot response_url does NOT support file message type
            # Only text/markdown messages are supported, so we skip file attachment sending
            # The cloud link in the text response is sufficient
            logger.info(f"[AIBOT_FILE] File available at cloud link (robot response_url does not support file attachments)")
            
            # 5. Final text cleanup (replace the entire tag with info) - Use ORIGINAL filename
            pattern_to_replace = re.escape(f'<FILE name="{original_filename}">') + r'[\s\S]*?' + re.escape('</FILE>')
            link_display = f"\n\n[已生成文件: {filename}]\n云端链接: {qiniu_url_display}"
            cleaned_content = re.sub(pattern_to_replace, link_display, cleaned_content, flags=re.IGNORECASE)
            
        except Exception as e:
            logger.error(f"[AIBOT_FILE] Error processing file {original_filename}: {e}")
            
    return cleaned_content


async def _call_llm_async(
    stream_id: str,
    bot_type: str,
    content: str,
    chat_id: str,
    user_id: str,
    user_name: str,
    wecom_msg_id: str | None,
    quoted_msg_id: str | None = None,
    quoted_filename: str | None = None,
    response_url: str | None = None,
) -> None:
    """Call the appropriate LLM asynchronously and update task result."""
    config = BOT_CONFIGS[bot_type]
    provider = config["provider"]
    system_prompt = config["system_prompt"]

    try:
        router = get_router()
        context_manager = get_context_manager()

        # Add user message to context (with dedup via wecom_msg_id)
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=user_id,
            sender_name=user_name or user_id,
            content=content,
            role="user",
            wecom_msg_id=wecom_msg_id,
            bot_type=bot_type,
        )

        # Get conversation history
        messages = context_manager.get_messages_for_llm(
            chat_id,
            system_prompt=system_prompt,
        )

        # 1. Quoted File (Specific)
        file_ctx = None
        if quoted_msg_id:
            # Try original ID first
            file_ctx = context_manager.get_active_file(chat_id, wecom_msg_id=quoted_msg_id)
            if not file_ctx:
                # Fallback: try derived image ID (file_{id}) to maintain vision quote matching
                file_ctx = context_manager.get_active_file(chat_id, wecom_msg_id=f"file_{quoted_msg_id}")
            
            if file_ctx:
                logger.info(f"[AIBOT_CTX] Found quoted file by MsgId: {file_ctx['filename']}")
        
        if not file_ctx and quoted_filename:
             file_ctx = context_manager.get_active_file(chat_id, filename=quoted_filename)
             if file_ctx:
                 logger.info(f"[AIBOT_CTX] Found quoted file by Filename: {file_ctx['filename']}")

        # 2. Latest File (Sticky/Global)
        if not file_ctx:
             file_ctx = context_manager.get_active_file(chat_id, limit=50)

        use_file_context = False
        if file_ctx:
             use_file_context = True
             logger.info(f"[AIBOT_CTX] Found file context for chat={chat_id}: {file_ctx['filename']} (UCS={not (file_ctx['uri'].startswith('content:') or file_ctx['uri'].startswith('base64:'))})")

        logger.info(
            f"[AIBOT_LLM_REQ] bot={bot_type} provider={provider} chat={chat_id} "
            f"user={user_name} msg_count={len(messages)} file_ctx={use_file_context} content={content[:50]!r}..."
        )

        start_time = time.time()
        loop = asyncio.get_running_loop()

        if use_file_context:
            try:
                # Format history for file chat (since chat_with_file takes text prompt)
                history_text = "\n\n".join(
                    [f"{'用户' if m['role']=='user' else '模型'}: {m['content']}" for m in messages]
                )
                
                # Check if file context is inline text or cloud URI
                file_uri = file_ctx["uri"]
                filename = file_ctx["filename"]
                
                if file_uri and file_uri.startswith("content:"):
                    # Inline Text Context
                    raw_content = file_uri[8:]
                    full_prompt = (
                        f"对话历史:\n{history_text}\n\n"
                        f"(注意：用户之前上传了文件 {filename}，内容如下，请基于此回答):\n"
                        f"```\n{raw_content}\n```\n\n用户新问题: {messages[-1]['content']}" # Last msg is current query
                        # Note: messages[-1] is already in history_text, but emphasizing it here helps
                    )
                    
                    response = await loop.run_in_executor(
                        None,
                        lambda: router.chat(
                            provider=provider,
                            messages=[{"role": "user", "content": full_prompt}]
                        )
                    )
                elif file_uri and file_uri.startswith("base64:"):
                    # Inline Base64 Context (PDF/Images)
                    raw_b64 = file_uri[7:]
                    file_bytes = base64.b64decode(raw_b64)
                    full_prompt = f"对话历史:\n{history_text}\n\n(注意：用户之前上传了文件 {filename}，请基于该文件回答)"
                    
                    response = await loop.run_in_executor(
                        None,
                        lambda: router.chat_with_file(
                            provider=provider,
                            text=full_prompt,
                            file_data=file_bytes,
                            file_mime_type=file_ctx["mime"],
                            filename=filename,
                            file_uri=None,
                            system_prompt=None, # Already in history
                        )
                    )
                else:
                    # Cloud URI Context (UCS Phase 1)
                    # For Qiniu/S3, we might need to download it first if the LLM doesn't support direct URLs
                    # Or for Gemini, if it's already a Gemini File API URI, use it directly.
                    
                    full_prompt = f"对话历史:\n{history_text}\n\n(注意：用户之前上传了文件 {filename}，请基于该文件回答)"
                    
                    is_gemini_uri = file_uri.startswith("https://generativelanguage.googleapis.com")
                    
                    if provider == "gemini" and is_gemini_uri:
                        # Use existing Gemini File API URI
                        response = await loop.run_in_executor(
                            None,
                            lambda: router.chat_with_file(
                                provider=provider,
                                text=full_prompt,
                                file_data=None, 
                                file_mime_type=file_ctx["mime"],
                                filename=filename,
                                file_uri=file_uri,
                            )
                        )
                    else:
                        try:
                            # Fix: Use signed URL for private buckets (Auditor Refinement)
                            storage = get_storage_manager()
                            storage_key = file_ctx.get("storage_key")
                            
                            if storage_key:
                                # Genuine cloud file with key -> Generate signed URL (1 hour)
                                signed_url = storage.get_url(storage_key, expires_in_seconds=3600)
                                logger.info(f"[AIBOT_CTX] Using signed URL for cloud access: {signed_url[:100]}...")
                            else:
                                # Legacy message (no key) -> Fallback to using URI directly
                                signed_url = file_uri
                                logger.info(f"[AIBOT_CTX] Fallback: using direct file URI (legacy context): {signed_url[:100]}...")
                            
                            # Use requests to download
                            # For local file://, use open()
                            if signed_url.startswith("file://"):
                                with open(signed_url[7:], "rb") as f:
                                    file_bytes = f.read()
                            else:
                                # Auditor Refinement: Security-first approach for cloud downloads
                                verify_ssl = os.getenv("STORAGE_VERIFY_SSL", "true").lower() == "true"
                                allow_fallback = os.getenv("STORAGE_ALLOW_HTTP_FALLBACK", "false").lower() == "true"
                                
                                if not verify_ssl:
                                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

                                try:
                                    download_res = requests.get(signed_url, timeout=30, verify=verify_ssl)
                                    download_res.raise_for_status()
                                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as ssl_err:
                                    # Only fallback to HTTP if explicitly allowed (e.g. for test/internal environments)
                                    if allow_fallback and "handshake failure" in str(ssl_err).lower() and signed_url.startswith("https://"):
                                        http_url = signed_url.replace("https://", "http://", 1)
                                        logger.warning(f"[AIBOT_CTX] SSL handshake failure, retrying with HTTP (opt-in fallback): {http_url[:100]}...")
                                        download_res = requests.get(http_url, timeout=30)
                                        download_res.raise_for_status()
                                    else:
                                        logger.error(f"[AIBOT_CTX] Download failed (SSL verify={verify_ssl}, fallback={allow_fallback}): {ssl_err}")
                                        raise
                                file_bytes = download_res.content
                            
                            response = await loop.run_in_executor(
                                None,
                                lambda: router.chat_with_file(
                                    provider=provider,
                                    text=full_prompt,
                                    file_data=file_bytes, 
                                    file_mime_type=file_ctx["mime"],
                                    filename=filename,
                                )
                            )
                        except Exception as download_err:
                            logger.error(f"[AIBOT_CTX] Failed to download cloud file: {download_err}")
                            raise download_err
            except Exception as e:
                logger.warning(f"[AIBOT_CTX] Failed to use file context (fallback to text): {e}")
                use_file_context = False
                # Auditor Suggestion: If file context was expected but failed, notify the user.
                context_error_hint = f"\n\n(注：无法加载历史图片/文件，本次回答仅基于文字记录。错误：{str(e)[:50]}...)"

        if not use_file_context:
            # Run standard LLM call
            response = await loop.run_in_executor(
                None, lambda: router.chat(provider=provider, messages=messages)
            )
            # Apply error hint if context failed
            if 'context_error_hint' in locals() and context_error_hint:
                response.content += context_error_hint

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"[AIBOT_LLM_RES] bot={bot_type} elapsed={elapsed_ms}ms "
            f"response_len={len(response.content)} content={response.content[:50]!r}..."
        )

        # Post-process response for generated files (Auditor Refinement)
        final_content = await _process_llm_file_output(
            bot_type=bot_type,
            chat_id=chat_id,
            content=response.content,
            user_id=user_id,
            user_name=user_name,
            response_url=response_url
        )

        # Add assistant response to context
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=f"bot_{bot_type}",
            sender_name=f"{bot_type}",
            content=final_content,
            role="assistant",
            bot_type=bot_type,
        )

        # Update task with completed response
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = final_content
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()

    except LLMError as e:
        logger.error(f"[AIBOT_LLM_ERR] bot={bot_type} error={e}")
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = (
                f"抱歉,AI服务暂时不可用: {str(e)[:50]}"
            )
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["error"] = True
    except Exception as e:
        logger.exception(f"[AIBOT_ERR] bot={bot_type} error={e}")
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = "抱歉,发生了意外错误,请稍后重试。"
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["error"] = True


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
                return await _handle_text_message(bot_type, data, nonce, timestamp, response_url=response_url)
            elif msgtype == "stream":
                return await _handle_stream_refresh(bot_type, data, nonce, timestamp)
            elif msgtype == "mixed":
                # Handle mixed messages (text + image combination)
                return await _handle_mixed_message(bot_type, data, nonce, timestamp, response_url=response_url)
            elif msgtype == "image":
                # Handle image-only messages
                return await _handle_image_message(bot_type, data, nonce, timestamp, response_url=response_url)
            elif msgtype == "file":
                # Handle file messages (PDF, Excel, etc.)
                return await _handle_file_message(bot_type, data, nonce, timestamp, response_url=response_url)
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
    # Cleanup old tasks on each message to prevent unbounded growth
    _cleanup_old_tasks()

    text_data = data.get("text", {})
    content = text_data.get("content", "").strip()

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))

    # Extract quoted message content if present
    quoted_content, quoted_msg_id = _extract_quote_content(data)
    original_content = content  # Save original user input
    quoted_filename = None
    
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
        for mark in ["[文件]", "[图片]", "📋", "📄"]:
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
    asyncio.create_task(
        _call_llm_async(
            stream_id=stream_id,
            bot_type=bot_type,
            content=content,
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            wecom_msg_id=wecom_msg_id,
            quoted_msg_id=quoted_msg_id,
            quoted_filename=quoted_filename,
            response_url=response_url,
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
        stream_json = _make_text_stream(stream_id, "任务已过期,请重新提问", finish=True)
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


def _extract_text_from_mixed(data: dict) -> str:
    """Extract text content from a mixed (image+text) message.

    Mixed messages contain a msg_item list with different content types.
    We extract all text content and combine it.
    """
    text_parts = []

    # Try msg_item array (common mixed message structure)
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "text":
                    text_obj = item.get("text", {})
                    if isinstance(text_obj, dict):
                        content = text_obj.get("content", "")
                        if content:
                            text_parts.append(content)
                    elif isinstance(text_obj, str):
                        text_parts.append(text_obj)

    # Also check for top-level text field as fallback
    if not text_parts:
        text_data = data.get("text", {})
        if isinstance(text_data, dict):
            content = text_data.get("content", "")
            if content:
                text_parts.append(content)
        elif isinstance(text_data, str):
            text_parts.append(text_data)

    return " ".join(text_parts).strip()


def _has_image_in_mixed(data: dict) -> bool:
    """Check if mixed message contains image content."""
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "image":
                    return True
    return False


def _extract_image_urls_from_mixed(data: dict) -> list[str]:
    """Extract image URLs from mixed message or image message.

    Returns a list of image URLs (encrypted) from the message.
    """
    urls = []

    # Check msg_item array (mixed message structure)
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "image":
                    image_data = item.get("image", {})
                    url = image_data.get("url", image_data.get("pic_url", ""))
                    if url:
                        urls.append(url)

    # Check top-level image field (image-only message)
    if not urls:
        image_data = data.get("image", {})
        url = image_data.get("url", image_data.get("pic_url", ""))
        if url:
            urls.append(url)

    return urls


def _upload_image_to_ucs(image_bytes: bytes) -> tuple[str | None, str | None, str, str]:
    """Upload image to cloud storage and detect correct MIME type/extension.
    
    Returns: (cloud_url, storage_key, mime_type, filename)
    """
    mime_type = "image/jpeg"
    ext = ".jpg"
    
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        mime_type = "image/png"
        ext = ".png"
    elif image_bytes.startswith(b'GIF8'):
        mime_type = "image/gif"
        ext = ".gif"
    elif image_bytes.startswith(b'\x42\x4d'):
        mime_type = "image/bmp"
        ext = ".bmp"
    elif image_bytes.startswith(b'\xff\xd8\xff'):
        mime_type = "image/jpeg"
        ext = ".jpg"
        
    filename = f"upload_{int(time.time())}{ext}"
    cloud_url = None
    storage_key = None
    
    try:
        storage = get_storage_manager()
        upload_res = storage.upload_file(image_bytes, filename, content_type=mime_type)
        cloud_url = upload_res.url
        storage_key = upload_res.key
        logger.info(f"[AIBOT_UCS] Uploaded image to cloud: {cloud_url} ({mime_type}, key={storage_key})")
    except Exception as e:
        logger.error(f"[AIBOT_UCS] Cloud upload failed: {e}")
        
    return cloud_url, storage_key, mime_type, filename


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
            logger.info(f"[AIBOT_DEDUP] bot={bot_type} msg_id={wecom_msg_id} returning existing stream_id={existing_stream_id}")
            stream_json = _make_text_stream(existing_stream_id, task["content"], task["finished"])
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
        return await _handle_text_message(bot_type, modified_data, nonce, timestamp, response_url=response_url)

    # Process with image - try to download and decrypt
    aes_key = _get_bot_aes_key(bot_type)
    image_base64 = None
    image_error = None
    file_url = None
    storage_key = None

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
            file_url, storage_key, _, _ = _upload_image_to_ucs(result)
        else:
            image_error = result
            logger.warning(f"[AIBOT_MIXED] bot={bot_type} image decrypt failed: {result}")

    # Build prompt
    if text_content:
        prompt = text_content
    else:
        prompt = "请描述这张图片的内容"

    # If image decryption failed, fall back to text-only
    if not image_base64:
        error_note = f"\n\n(注: 图片处理失败: {image_error})" if image_error else ""
        modified_data = data.copy()
        modified_data["text"] = {"content": prompt + error_note}
        modified_data["msgtype"] = "text"
        return await _handle_text_message(bot_type, modified_data, nonce, timestamp, response_url=response_url)

    # Process with image using vision API
    return await _handle_vision_message(
        bot_type, data, nonce, timestamp, prompt, image_base64, user_id, user_name, file_url, storage_key, stream_id, response_url=response_url
    )


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
            logger.info(f"[AIBOT_DEDUP] bot={bot_type} image msg_id={wecom_msg_id} returning cached response")
            stream_json = _make_text_stream(existing_stream_id, task["content"], task["finished"])
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
        response_text = "收到您的消息，但未找到图片内容。请重新发送图片。"
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
        response_text = f"收到您的图片，但处理时出现问题：{result}\n\n请稍后重试，或添加文字说明。"
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
    file_url, storage_key, _, _ = _upload_image_to_ucs(result)

    logger.info(f"[AIBOT_IMAGE] bot={bot_type} image ready, sending to vision API")

    return await _handle_vision_message(
        bot_type, data, nonce, timestamp, prompt, image_base64, user_id, user_name, file_url, storage_key, stream_id, response_url=response_url
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
            logger.info(f"[AIBOT_VISION] Returning cached response for msgid={wecom_msg_id}")
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

            # Fix: Use a derived message ID for the file context to avoid conflict with the user message (persistence dedup)
            file_msg_id = f"file_{wecom_msg_id}" if wecom_msg_id else None
            get_context_manager().save_file(
                chat_id=chat_id,
                sender_id=user_id,
                sender_name=user_name,
                file_uri=file_url,
                filename=filename,
                mime_type=mime_type,
                wecom_msg_id=file_msg_id,
                bot_type=bot_type,
                storage_key=storage_key,
            )
            logger.info(f"[AIBOT_VISION] Saved persistent image context for chat={chat_id} (msgid={file_msg_id})")
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
        )
    )

    # Return immediate "analyzing" response
    stream_json = _make_text_stream(stream_id, "正在分析图片...", finish=False)
    encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)

    logger.info(f"[AIBOT_VISION] bot={bot_type} stream_id={stream_id} analyzing image")
    return Response(content=encrypted, media_type="text/plain")


async def _call_vision_llm_async(
    stream_id: str,
    bot_type: str,
    provider: str,
    prompt: str,
    image_base64: str,
    system_prompt: str,
    chat_id: str,
    user_id: str,
    user_name: str,
    wecom_msg_id: str | None = None,
    quoted_msg_id: str | None = None,
    response_url: str | None = None,
) -> None:
    """Call vision LLM asynchronously and update task result."""
    try:
        router = get_router()
        context_manager = get_context_manager()

        # Add user message to context (Auditor parity)
        context_manager.add_message(
            chat_id=chat_id,
            sender_id=user_id,
            sender_name=user_name or user_id,
            content=prompt,
            role="user",
            wecom_msg_id=wecom_msg_id,
            bot_type=bot_type,
        )

        logger.info(
            f"[AIBOT_VISION_REQ] bot={bot_type} provider={provider} "
            f"prompt={prompt[:50]!r}... image_size={len(image_base64)//1024}KB"
        )

        start_time = time.time()

        # Run vision LLM call in thread pool
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: router.chat_with_image(
                provider=provider,
                text=prompt,
                image_base64=image_base64,
                system_prompt=system_prompt,
            )
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"[AIBOT_VISION_RES] bot={bot_type} elapsed={elapsed_ms}ms "
            f"response_len={len(response.content)}"
        )

        # Post-process response for generated files (Auditor Refinement)
        final_content = await _process_llm_file_output(
            bot_type=bot_type,
            chat_id=chat_id,
            content=response.content,
            user_id=user_id,
            user_name=user_name,
            response_url=response_url
        )

        # Update task with completed response
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = final_content
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()

    except LLMError as e:
        logger.error(f"[AIBOT_VISION_ERR] bot={bot_type} error={e}")
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = (
                f"抱歉，图片分析服务暂时不可用: {str(e)[:100]}"
            )
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()

    except Exception as e:
        logger.exception(f"[AIBOT_VISION_ERR] bot={bot_type} unexpected error: {e}")
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = "图片分析时发生错误，请稍后重试。"
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()


def _extract_file_info(data: dict) -> tuple[str | None, str, str]:
    """Extract file URL, filename and mimetype from message.
    
    Returns: (url, filename, mimetype)
    """
    # Deep search for filename-like keys
    def deep_find_filename(obj):
        if not isinstance(obj, dict):
            return None
        # Priority keys
        for k in ["filename", "name", "title", "file_name"]:
            if k in obj and obj[k] and isinstance(obj[k], str) and "." in obj[k]:
                return obj[k]
        # Recursion
        for v in obj.values():
            if isinstance(v, dict):
                res = deep_find_filename(v)
                if res: return res
            elif isinstance(v, list):
                for item in v:
                    res = deep_find_filename(item)
                    if res: return res
        return None

    filename = deep_find_filename(data)
    
    # Try to extract from URL if still unknown
    url = data.get("url")
    if not isinstance(url, str):
        file_obj = data.get("file", {})
        if isinstance(file_obj, dict):
            url = file_obj.get("url")
            
    if not filename and url:
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path
            filename = os.path.basename(path)
            if not "." in filename:
                filename = None
        except:
            pass
            
    if not filename:
        filename = "文档"

    file_data = data.get("file", {})
    ext = ""
    if isinstance(file_data, dict):
        ext = file_data.get("file_ext", "")
    if not ext:
        ext = data.get("file_ext", "")
    
    if ext and filename != "文档" and not filename.endswith(f".{ext}"):
        filename = f"{filename}.{ext}"
        
    logger.info(f"[AIBOT_FILE_EXTRACT] Deep search filename={filename} ext={ext}")
        
    mime_type, _ = mimetypes.guess_type(filename) if filename != "文档" else (None, None)
    if not mime_type:
        mime_type = "application/octet-stream"
        
    return url, filename, mime_type


async def _handle_file_message(
    bot_type: str,
    data: dict,
    nonce: str,
    timestamp: str,
    response_url: str | None = None,
) -> Response:
    """Handle file messages (PDF, Excel, Word).
    
    Downloads decrypted file and sends to Gemini for analysis.
    For other bots, returns a friendly 'not supported' message.
    """
    _cleanup_old_tasks()

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))
    
    wecom_msg_id = _extract_msg_id(data)
    _, quoted_msg_id = _extract_quote_content(data)
    if wecom_msg_id and wecom_msg_id in _processed_messages:
        existing_stream_id = _processed_messages[wecom_msg_id]
        task = _stream_tasks.get(existing_stream_id)
        if task:
            logger.info(f"[AIBOT_DEDUP] bot={bot_type} file msg_id={wecom_msg_id} returning cached response")
            stream_json = _make_text_stream(existing_stream_id, task["content"], task["finished"])
            encrypted = _encrypt_response(bot_type, stream_json, nonce, timestamp)
            return Response(content=encrypted, media_type="text/plain")
    stream_id = _generate_stream_id()

    # Extract file info
    url, filename, mime_type = _extract_file_info(data)
    
    logger.info(f"[AIBOT_FILE] bot={bot_type} user={user_name} file={filename} mime={mime_type} raw_data={json.dumps(data, ensure_ascii=False)}")
    
    chat_id = _extract_chat_id(data, user_id)
    
    # Check bot support
    config = BOT_CONFIGS[bot_type]
    provider = config.get("provider", "openai")

    # Support check: All bots now support at least PDF/Text via fallback
    # But Gemini is still the preferred provider for native multi-modal docs.
    if provider != "gemini" and mime_type != "application/pdf" and not mime_type.startswith("text/"):
        response_text = (
            f"收到文件：{filename}\n\n"
            f"抱歉，目前的“大文档原生分析”能力仅在 Gemini 系列机器人上可用。{bot_type} 目前仅额外支持 PDF 和 纯文本分析。"
        )
        _stream_tasks[stream_id] = {
            "content": response_text,
            "finished": True,
            "created_at": time.time(),
            "bot_type": bot_type,
            "chat_id": chat_id,
            "user_id": user_id,
        }
        stream_json = _make_text_stream(stream_id, response_text, finish=True)
        return Response(content=_encrypt_response(bot_type, stream_json, nonce, timestamp), media_type="text/plain")

    if not url:
        logger.warning(f"[AIBOT_FILE] bot={bot_type} No file URL found in {data}")
        response_text = f"收到文件：{filename}\n\n无法获取文件下载链接，请稍后重试。"
        _stream_tasks[stream_id] = {
            "content": response_text,
            "finished": True,
            "created_at": time.time(),
            "bot_type": bot_type,
            "chat_id": chat_id,
            "user_id": user_id,
        }
        stream_json = _make_text_stream(stream_id, response_text, finish=True)
        return Response(content=_encrypt_response(bot_type, stream_json, nonce, timestamp), media_type="text/plain")
        
    # Start processing task
    if wecom_msg_id:
        _processed_messages[wecom_msg_id] = stream_id
        
    _stream_tasks[stream_id] = {
        "content": f"正在下载并分析文档：{filename} ...",
        "finished": False,
        "created_at": time.time(),
        "bot_type": bot_type,
        "chat_id": chat_id,
        "user_id": user_id,
        "wecom_msg_id": wecom_msg_id,
    }
    
    # Start async download and analysis
    asyncio.create_task(
        _call_file_llm_async(
            stream_id=stream_id,
            bot_type=bot_type,
            provider=provider,
            file_url=url,
            filename=filename,
            mime_type=mime_type,
            system_prompt=config["system_prompt"],
            user_id=user_id,
            chat_id=chat_id,
            wecom_msg_id=wecom_msg_id,
            quoted_msg_id=quoted_msg_id,
            response_url=response_url,
        )
    )
    
    stream_json = _make_text_stream(stream_id, f"正在分析文档：{filename} ...", finish=False)
    return Response(content=_encrypt_response(bot_type, stream_json, nonce, timestamp), media_type="text/plain")


async def _call_file_llm_async(
    stream_id: str,
    bot_type: str,
    provider: str,
    file_url: str,
    filename: str,
    mime_type: str,
    system_prompt: str,
    user_id: str,
    chat_id: str,
    wecom_msg_id: str | None = None,
    quoted_msg_id: str | None = None,
    response_url: str | None = None,
) -> None:
    """Download file, upload to LLM, and generate analysis."""
    try:
        router = get_router()
        aes_key = _get_bot_aes_key(bot_type)
        
        if not aes_key:
            raise ValueError(f"AES Key not found for {bot_type}")

        success, media_data = _decrypt_media(file_url, aes_key)
        if not success:
            raise ValueError(f"File download failed: {media_data}")
            
        file_bytes = media_data if isinstance(media_data, bytes) else media_data.encode("utf-8")
        
        # 1.5 Robust MIME Type Detection (Gemini 3 is strict about this for inline_data)
        original_mime = mime_type
        
        # If filename is generic or missing, try magic bytes
        if filename in ["unknown_file", "文档", "file"]:
            if file_bytes.startswith(b'%PDF-'):
                mime_type = "application/pdf"
                filename = "document.pdf"
            else:
                try:
                    file_bytes.decode('utf-8')
                    mime_type = "text/plain"
                    filename = "content.txt"
                except:
                    # Keep as is, or default to octet-stream
                    pass
        
        # Trust extension more than WeCom's reported mime_type
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            mime_type = "application/pdf"
        elif ext in ['.sql', '.py', '.js', '.ts', '.html', '.css', '.md', '.json', '.xml', '.sh', '.yaml', '.yml', '.c', '.cpp', '.java', '.go', '.rs', '.php', '.txt']:
            mime_type = "text/plain"
        elif not mime_type or mime_type == "application/octet-stream":
            guessed = mimetypes.guess_type(filename)[0]
            if guessed:
                mime_type = guessed
        
        logger.info(f"[AIBOT_FILE_REQ] bot={bot_type} file={filename} size={len(file_bytes)} original_mime={original_mime} final_mime={mime_type}")
        
        prompt = f"请详细分析这份文档的内容：{filename}"
        
        start_time = time.time()
        loop = asyncio.get_running_loop()

        # 2. Upload file OR Prepare inline content
        file_uri = None
        is_inline_text = False
        
        # Check if it is a code/text file suitable for inline processing
        ext = os.path.splitext(filename)[1].lower()
        is_code_file = ext in ['.sql', '.py', '.js', '.ts', '.html', '.css', '.txt', '.md', '.json', '.xml', '.sh', '.yaml', '.yml', '.c', '.cpp', '.java', '.go', '.rs', '.php']
        
        if is_code_file:
            try:
                # 1. Try decoding with specific encodings
                text_content = None
                for enc in ['utf-8', 'gbk', 'gb18030', 'iso-8859-1']:
                    try:
                        text_content = file_bytes.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                
                # 2. Safe Fallback
                if text_content is None:
                    text_content = file_bytes.decode('utf-8', errors='replace')
                    logger.warning(f"Used lossy decoding for {filename}")

                # 3. Validation
                if not text_content:
                    text_content = "<Empty File>"

                # 4. Success -> Inline Text
                file_uri = f"content:{text_content}"
                is_inline_text = True
                logger.info(f"[AIBOT_FILE] Treating {filename} as inline text ({len(text_content)} chars)")

            except Exception as e:
                logger.error(f"Decoding error for {filename}: {e}. Fallback to Safe Decode.")
                # EMERGENCY FALLBACK: Force decode
                try:
                    safe_text = file_bytes.decode('utf-8', errors='replace')
                    file_uri = f"content:{safe_text}"
                    is_inline_text = True
                except:
                   # Only if everything fails, allow fallback (likely 400)
                   is_code_file = False

        if not is_code_file and provider == "gemini":
            try:
                # Use Inline Data (Base64) for files under 20MB (Verified working for gemini-3)
                if len(file_bytes) < 20 * 1024 * 1024:
                    b64_data = base64.b64encode(file_bytes).decode('utf-8')
                    file_uri = f"base64:{b64_data}"
                    logger.info(f"[AIBOT_FILE] Prepared Inline Data (base64) for {filename} ({len(file_bytes)} bytes)")
                else:
                    # Fallback to standard File API for larger files
                    file_uri = await loop.run_in_executor(
                        None, 
                        lambda: router.upload_file(provider, file_bytes, mime_type, filename)
                    )
                    logger.info(f"[AIBOT_FILE] Uploaded large file {filename} to Gemini File API: {file_uri}")
            except Exception as e:
                logger.error(f"Failed to process Gemini file {filename}: {e}")
                # Emergency fallback to inline text if upload fails
                is_code_file = True
                try:
                    text_content = file_bytes.decode('utf-8', errors='replace')
                    file_uri = f"content:{text_content}"
                    is_inline_text = True
                except:
                    pass

        # 2.5 Cloud Storage Upload (UCS Phase 1)
        cloud_url = None
        cloud_key = None
        try:
            storage = get_storage_manager()
            upload_res = storage.upload_file(file_bytes, filename, content_type=mime_type)
            cloud_url = upload_res.url
            cloud_key = upload_res.key
            logger.info(f"[AIBOT_FILE] Uploaded file to cloud: {cloud_url} (key={cloud_key})")
        except Exception as e:
            logger.error(f"[AIBOT_FILE] Cloud upload failed: {e}")

        # 3. Save context for future turns (PERSISTENT - UCS Phase 1)
        # We ALWAYS store the cloud URL in the DB if available, for cross-bot access.
        # If cloud upload failed, we fallback to storing the temporary file_uri.
        # Fix: Prevent DB bloat if fallback is a large Base64 blob.
        db_file_uri = cloud_url or file_uri
        should_save = True
        if not cloud_url and db_file_uri and db_file_uri.startswith("base64:"):
            if len(db_file_uri) > 1 * 1024 * 1024: # Limit to 1MB total (approx 750KB data)
                logger.warning(f"[AIBOT_CTX] Skipping DB persistence for large Base64 fallback ({len(db_file_uri)} chars)")
                should_save = False

        if db_file_uri and should_save:
            get_context_manager().save_file(
                chat_id=chat_id,
                user_id=user_id,
                sender_name=user_id,
                file_uri=db_file_uri,
                filename=filename,
                mime_type=mime_type,
                wecom_msg_id=wecom_msg_id,
                bot_type=bot_type,
                storage_key=cloud_key,
            )
            logger.info(f"[AIBOT_CTX] Saved persistent file context for chat={chat_id} (UCS={bool(cloud_url)})")

        # 4. Call LLM
        if is_inline_text:
            # Chat directly with text content
            # Ensure file_uri is not None before slicing
            raw_text = file_uri[8:] if (file_uri and file_uri.startswith("content:")) else "<Error: Text missing>"
            full_prompt = f"请分析以下文件内容 ({filename}):\n\n```\n{raw_text}\n```\n\n{prompt}"
            response = await loop.run_in_executor(
                None,
                lambda: router.chat(
                    provider=provider,
                    messages=[{"role": "user", "content": full_prompt}]
                )
            )
        else:
            # Chat with Cloud URI or Base64 URI
            real_file_data = file_bytes # Fix: Always pass file_bytes if we have it (for non-Gemini PDF fallback)
            real_file_uri = file_uri
            
            if file_uri and file_uri.startswith("base64:"):
                # Use data from URI if it's already base64 (redundant but safe)
                real_file_data = base64.b64decode(file_uri[7:])
                real_file_uri = None
            
            response = await loop.run_in_executor(
                None,
                lambda: router.chat_with_file(
                    provider=provider,
                    text=prompt, 
                    file_data=real_file_data,
                    file_uri=real_file_uri,
                    file_mime_type=mime_type,
                    filename=filename, # Include filename for better context
                    system_prompt=system_prompt,
                )
            )

        
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(f"[AIBOT_FILE_RES] bot={bot_type} elapsed={elapsed_ms}ms")
        
        # Post-process response for generated files (Auditor Refinement)
        final_content = await _process_llm_file_output(
            bot_type=bot_type,
            chat_id=chat_id,
            content=response.content,
            user_id=user_id,
            user_name=None, # user_name not in scope here
            response_url=response_url
        )

        # Update task with completed response
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = final_content
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()
            
    except Exception as e:
        logger.exception(f"[AIBOT_FILE_ERR] bot={bot_type} error: {e}")
        if stream_id in _stream_tasks:
            _stream_tasks[stream_id]["content"] = f"文档分析失败：{str(e)[:100]}"
            _stream_tasks[stream_id]["finished"] = True
            _stream_tasks[stream_id]["completed_at"] = time.time()
