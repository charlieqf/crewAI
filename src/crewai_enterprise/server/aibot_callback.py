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
from src.crewai_enterprise.flows.code_review_flow import CodeReviewFlow
from src.crewai_enterprise.flows.codebase_qa_flow import CodebaseQAFlow
from src.crewai_enterprise.tools.archive.archive_tool import get_merged_chat_history
from src.crewai_enterprise.utils.report_generator import generate_html_report

# Global cache for user project context (chat_id -> {project_path, gitlab_url})
# In production, this should be in Redis
_user_project_context: dict[str, dict[str, str]] = {}

# Predefined project nicknames to bypass WeCom URL filtering
# Usage: @gemini /codebase <nickname> <question>
PROJECT_NICKNAMES = {
    "qd": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan"
    },
    "quick-deal": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan"
    },
    "project-meituan": {
        "project_path": "qd-team/quick-deal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "project-meituan"
    },
    "investorportal": {
        "project_path": "didi/investorportal",
        "gitlab_url": "http://gitlab.goldenstand.com",
        "branch": "master"
    }
}


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


def _detect_daily_report_intent(text: str) -> bool:
    """Detect if the user is requesting a daily/group summary."""
    keywords = [
        r"daily", r"today", r"summary", r"report", r"group chat", 
        r"报告", r"总结", r"今天", r"群聊", r"内容", r"干了什么", r"纪要"
    ]
    # Check for direct file-html context or keywords
    for kw in keywords:
        if re.search(kw, text, re.IGNORECASE):
            return True
    return False


def _format_chat_history(history: list[dict]) -> str:
    """Formats merged chat history for LLM prompt."""
    lines = []
    for msg in history:
        time_str = msg.get("timestamp", "")
        if " " in time_str:
            time_str = time_str.split(" ")[1][:5]
        else:
            time_str = time_str[:5]
        
        sender = msg.get("sender", "未知")
        content = msg.get("content", "")
        role_label = ""
        if msg.get("role") == "assistant":
            role_label = "[Bot]"
        
        lines.append(f"[{time_str}] {role_label}{sender}: {content}")
    
    return "\n".join(lines)

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



def _generate_stream_id() -> str:
    """Generate a unique stream ID for task tracking."""
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _sanitize_text(text: str) -> str:
    """Remove hidden/invisible characters from text that may come from WeCom copy-paste.
    
    This cleans:
    - Zero-width spaces (U+200B, U+200C, U+200D, U+FEFF)
    - Various invisible Unicode characters
    - Normalizes whitespace (full-width to half-width)
    """
    if not text:
        return text
    
    # Characters to remove completely
    invisible_chars = [
        '\u200b',  # Zero-width space
        '\u200c',  # Zero-width non-joiner
        '\u200d',  # Zero-width joiner
        '\ufeff',  # BOM / Zero-width no-break space
        '\u00a0',  # Non-breaking space (replace with regular space)
        '\u3000',  # Ideographic space (full-width space)
        '\u2028',  # Line separator
        '\u2029',  # Paragraph separator
    ]
    
    result = text
    for char in invisible_chars:
        result = result.replace(char, ' ' if char in ['\u00a0', '\u3000'] else '')
    
    # Normalize multiple spaces to single space
    result = ' '.join(result.split())
    
    return result



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
    content: str, 
    chat_id: str, 
    bot_type: str, 
    user_id: str | None = None,
    user_name: str | None = None,
    response_url: str | None = None,
    file_only_mode: bool = False,
    is_report_request: bool = False,
    template_name: str | None = None,
    raw_context: str | None = None,
) -> str:
    """Detect and process <FILE> tags in LLM output.
    
    Args:
        file_only_mode: If True, return only the cloud link (no extra text).
        is_report_request: If True, allow auto-conversion of JSON to HTML report.
        template_name: Template to use for JSON rendering ('daily', 'meeting', or None for free-form).
        raw_context: Raw chat context to append to HTML for debugging/transparency.
    """
    import re
    from datetime import datetime
    from src.crewai_enterprise.utils.file_storage import get_file_manager
    from src.crewai_enterprise.utils.storage_manager import get_storage_manager
    from src.crewai_enterprise.utils.chat_context import get_context_manager
    
    # Template-based JSON-to-HTML rendering
    # For template modes (daily, meeting), the LLM outputs structured JSON
    # which gets rendered via the corresponding HTML template
    if template_name in ("daily", "meeting"):
        try:
            from datetime import timedelta, timezone
            BEIJING_TZ = timezone(timedelta(hours=8))
            now_bj = datetime.now(BEIJING_TZ)

            logger.info(f"[AIBOT_TEMPLATE] Rendering {template_name} template for chat={chat_id}")
            html_report, success = generate_html_report(content, chat_id, template_name=template_name, raw_context=raw_context)
            
            if success:
                # Successfully converted JSON to HTML via template
                storage = get_storage_manager()
                filename_prefix = "daily_report" if template_name == "daily" else "meeting_notes"
                report_filename = f"{filename_prefix}_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                upload_res = storage.upload_file(
                    html_report.encode("utf-8"), 
                    report_filename, 
                    content_type="text/html"
                )
                logger.info(f"[AIBOT_TEMPLATE] Uploaded {template_name} report to cloud: {upload_res.url}")
                
                emoji = "📋" if template_name == "daily" else "📝"
                label = "每日群聊摘要报告" if template_name == "daily" else "会议纪要"
                
                # Generate content-specific description by parsing JSON
                try:
                    import json
                    clean_json = content.strip()
                    if "```json" in clean_json:
                        clean_json = clean_json.split("```json")[-1].split("```")[0].strip()
                    data = json.loads(clean_json)
                    
                    if template_name == "daily":
                        topics_count = len(data.get("topics", []))
                        todos_count = len(data.get("todos", []))
                        desc = f"提取了{topics_count}个讨论话题和{todos_count}个待办事项"
                    else:
                        agenda_count = len(data.get("agenda", []))
                        actions_count = len(data.get("action_items", []))
                        desc = f"整理了{agenda_count}个议程项目和{actions_count}个行动项"
                except:
                    desc = "已生成"
                
                # Never echo raw JSON content - only return link with description
                return f"{emoji} {label}：{desc}\n📄 云端链接: {upload_res.url}"
            else:
                # Template rendering failed - return error HTML instead of falling back
                logger.warning(f"[AIBOT_TEMPLATE] Template rendering failed for {template_name}, returning error report")
                storage = get_storage_manager()
                report_filename = f"error_report_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                upload_res = storage.upload_file(
                    html_report.encode("utf-8"),  # html_report contains error HTML from render_template
                    report_filename,
                    content_type="text/html"
                )
                return f"❌ 模板渲染失败，请检查输出格式：\n{upload_res.url}"
        except Exception as e:
            logger.error(f"[AIBOT_TEMPLATE] Failed to render {template_name} template: {e}")
            # Return error message instead of falling back
            return f"❌ 生成报告时出错: {str(e)[:100]}..."
    
    # Legacy: Auto-conversion for daily report intent detection (backward compatibility)
    elif is_report_request and "topics" in content and "todos" in content and "{" in content:
        try:
            from datetime import timedelta, timezone
            BEIJING_TZ = timezone(timedelta(hours=8))
            now_bj = datetime.now(BEIJING_TZ)

            logger.info(f"[AIBOT_REPORT] Detected potential JSON report, converting to HTML for chat={chat_id}")
            html_report, success = generate_html_report(content, chat_id, template_name="daily")
            
            if success:
                # Successfully converted JSON report to HTML
                storage = get_storage_manager()
                report_filename = f"daily_report_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                upload_res = storage.upload_file(
                    html_report.encode("utf-8"), 
                    report_filename, 
                    content_type="text/html"
                )
                logger.info(f"[AIBOT_REPORT] Uploaded generated report to cloud: {upload_res.url}")
                
                # Generate content-specific description (same as template path)
                try:
                    import json
                    clean_json = content.strip()
                    if "```json" in clean_json:
                        clean_json = clean_json.split("```json")[-1].split("```")[0].strip()
                    data = json.loads(clean_json)
                    topics_count = len(data.get("topics", []))
                    todos_count = len(data.get("todos", []))
                    desc = f"提取了{topics_count}个讨论话题和{todos_count}个待办事项"
                except:
                    desc = "已生成"
                
                # Never echo raw JSON - consistent with template path
                return f"📋 每日群聊摘要报告：{desc}\n📄 云端链接: {upload_res.url}"
            else:
                logger.warning(f"[AIBOT_REPORT] HTML conversion success=False for chat={chat_id}, bypassing auto-upload.")
        except Exception as e:
            logger.error(f"[AIBOT_REPORT] Failed to auto-convert report JSON: {e}")


    # Robust parsing: Find all opening tags first
    # This handles cases where a tag might be opened but not closed (truncated output)
    open_tag_pattern = re.compile(r'<FILE\s+name="([^"]+)">', re.IGNORECASE)
    open_tags = list(open_tag_pattern.finditer(content))
    
    if not open_tags:
        # Fallback: If we are in file_only_mode but no tags were found, 
        # it means the LLM might have outputted the content directly without tags.
        # We auto-wrap it into a default report.html
        if file_only_mode and content.strip():
            logger.info(f"[AIBOT_FILE] No <FILE> tags found in file_only_mode, initiating auto-wrap fallback for chat={chat_id}")
            
            # Simple check if it looks like HTML
            is_html = content.strip().lower().startswith("<!doctype") or "<html" in content.lower()
            
            if is_html:
                file_content = content
            else:
                # Wrap markdown/text in a basic Tailwind terminal-style container for consistency
                file_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Generated Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0f172a] text-slate-200 min-h-screen p-4 md:p-8">
    <div class="max-w-4xl mx-auto bg-[#1e293b] rounded-xl shadow-2xl border border-slate-700 overflow-hidden">
        <div class="bg-[#334155] px-4 py-2 flex items-center gap-2 border-b border-slate-700">
            <div class="flex gap-1.5">
                <div class="w-2.5 h-2.5 rounded-full bg-red-400"></div>
                <div class="w-2.5 h-2.5 rounded-full bg-amber-400"></div>
                <div class="w-2.5 h-2.5 rounded-full bg-emerald-400"></div>
            </div>
            <span class="text-xs text-slate-400 font-mono ml-2">generated_report.html</span>
        </div>
        <div class="p-6 md:p-8 font-sans leading-relaxed whitespace-pre-wrap">
{content}
        </div>
    </div>
</body>
</html>"""
            
            # Process the auto-wrapped content immediately
            filename = "generated_report.html"
            file_manager = get_file_manager()
            storage = get_storage_manager()
            context_manager = get_context_manager()
            
            # Proceed with the same injection and upload logic
            # 1. Save locally
            file_info = file_manager.save_file_from_bytes(
                chat_id=chat_id,
                content=file_content.encode("utf-8"),
                filename=filename
            )
            
            # 2. Upload
            mime_type = "text/html"
            final_content = file_content
            if raw_context:
                import html as html_module
                import re as re_mod
                escaped_context = html_module.escape(raw_context)
                context_section = f'''
<hr style="margin-top: 40px; border: 1px dashed #ccc;">
<details style="margin-top: 20px; padding: 15px; background: #1a1a2e; border-radius: 8px;">
<summary style="cursor: pointer; color: #8b8b9e; font-size: 14px;">
  📋 原始上下文数据（用于生成本报告的聊天记录）
</summary>
<pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 12px; color: #a0a0b0; margin-top: 10px; max-height: 500px; overflow-y: auto;">
{escaped_context}
</pre>
</details>
'''
                body_matches = list(re_mod.finditer(r'</body>', final_content, re_mod.IGNORECASE))
                if body_matches:
                    last_body = body_matches[-1]
                    final_content = final_content[:last_body.start()] + context_section + final_content[last_body.start():]
                elif '</html>' in final_content.lower():
                    html_matches = list(re_mod.finditer(r'</html>', final_content, re_mod.IGNORECASE))
                    if html_matches:
                        last_html = html_matches[-1]
                        final_content = final_content[:last_html.start()] + context_section + final_content[last_html.start():]
                else:
                    final_content += context_section
            
            upload_res = storage.upload_file(
                data=final_content.encode("utf-8"),
                filename=filename,
                content_type=mime_type
            )
            
            # 3. Save Context
            context_manager.save_file(
                chat_id=chat_id,
                sender_id=f"bot_{bot_type}",
                sender_name=bot_type,
                file_uri=upload_res.url,
                filename=filename,
                mime_type=mime_type,
                bot_type=bot_type,
                storage_key=upload_res.key
            )
            
            # Return summary + link
            # Try to extract a summary from the beginning of the content
            summary = content.strip().split('\n')[0]
            if len(summary) > 60:
                summary = summary[:57] + "..."
                
            return f"{summary}\n📄 云端链接: {upload_res.url}"
        else:
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

    # Process tags from last to first to maintain correct string indices after replacement
    for i in range(len(open_tags) - 1, -1, -1):
        match = open_tags[i]
        original_filename = match.group(1)
        start_pos = match.end()
        
        # Determine end of file content (either next opening tag or end of string)
        # But we also search for a closing tag within this range
        next_tag_start = open_tags[i+1].start() if i + 1 < len(open_tags) else len(content)
        segment = content[start_pos:next_tag_start]
        
        closing_match = re.search(r'</FILE>', segment, re.IGNORECASE)
        if closing_match:
            file_content = segment[:closing_match.start()]
            full_tag_end_pos = start_pos + closing_match.end()
        else:
            # Fallback for truncated/unclosed tags: take until next tag or end
            file_content = segment
            full_tag_end_pos = next_tag_start
            logger.warning(f"[AIBOT_FILE] Tag for {original_filename} was not closed, taking content until end/next tag")

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
                mime_type = "text/html" if filename.endswith(".html") or filename.endswith(".htm") else "text/plain"
                
                # Append raw_context to HTML files for transparency
                final_content = file_content
                if raw_context and mime_type == "text/html":
                    import html as html_module
                    import re
                    escaped_context = html_module.escape(raw_context)
                    context_section = f'''
<hr style="margin-top: 40px; border: 1px dashed #ccc;">
<details style="margin-top: 20px; padding: 15px; background: #1a1a2e; border-radius: 8px;">
<summary style="cursor: pointer; color: #8b8b9e; font-size: 14px;">
  📋 原始上下文数据（用于生成本报告的聊天记录）
</summary>
<pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 12px; color: #a0a0b0; margin-top: 10px; max-height: 500px; overflow-y: auto;">
{escaped_context}
</pre>
</details>
'''
                    # Find the LAST </body> tag to ensure we're at the true document end
                    body_matches = list(re.finditer(r'</body>', final_content, re.IGNORECASE))
                    if body_matches:
                        last_body = body_matches[-1]
                        final_content = final_content[:last_body.start()] + context_section + final_content[last_body.start():]
                    elif '</html>' in final_content.lower():
                        # Fallback: insert before </html>
                        html_matches = list(re.finditer(r'</html>', final_content, re.IGNORECASE))
                        if html_matches:
                            last_html = html_matches[-1]
                            final_content = final_content[:last_html.start()] + context_section + final_content[last_html.start():]
                    else:
                        # Last resort: append to end
                        final_content += context_section
                    logger.info(f"[AIBOT_FILE] Appended raw_context ({len(raw_context)} chars) to HTML")
                
                upload_res = storage.upload_file(
                    data=final_content.encode("utf-8"),
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
            
            # 5. Final text cleanup (replace the entire tag with info)
            # Extract summary: first line of text before the first <FILE> tag
            summary_text = ""
            if i == 0:  # Only extract summary for the first file
                pre_tag_content = content[:match.start()].strip()
                if pre_tag_content:
                    # Take only the first line, truncate to 100 chars
                    first_line = pre_tag_content.split('\n')[0].strip()
                    if len(first_line) > 100:
                        summary_text = first_line[:97] + "..."
                    else:
                        summary_text = first_line
                    logger.info(f"[AIBOT_FILE] Extracted summary: {summary_text}")
            
            if file_only_mode:
                # In file_only_mode, return link + summary (with fallback)
                if summary_text:
                    return f"📄 云端链接: {qiniu_url_display}\n✨ {summary_text}"
                else:
                    # Fallback description when LLM omits summary
                    return f"📄 云端链接: {qiniu_url_display}\n✨ 已生成HTML文件"
            else:
                if summary_text:
                    link_display = f"\n\n✨ {summary_text}\n📄 云端链接: {qiniu_url_display}"
                else:
                    # Fallback description when LLM omits summary
                    link_display = f"\n\n✨ 已生成HTML文件\n📄 云端链接: {qiniu_url_display}"
                cleaned_content = cleaned_content[:match.start()] + link_display + cleaned_content[full_tag_end_pos:]
            
        except Exception as e:
            logger.error(f"[AIBOT_FILE] Error processing file {original_filename}: {e}")
            
    return cleaned_content


def _handle_prompt_command(
    command: str,
    args: str,
    bot_type: str,
    chat_id: str,
    user_id: str,
) -> dict | None:
    """Handle prompt management and bot commands.
    
    Args:
        command: Command name (show_prompt, set_prompt, reset_prompt, new, codebase, help)
        args: Command arguments (for set_prompt, codebase)
        bot_type: Bot identifier
        chat_id: Chat ID
        user_id: User ID
    
    Returns:
        dict with 'content' key containing response message, or None if command not recognized
    """
    context_manager = get_context_manager()
    
    if command == "help":
        # Show help message with all available commands
        help_text = """🤖 **AI Bot 使用指南**

**💬 Prompt 管理命令：**
• `/show_prompt` - 查看当前系统提示词
• `/set_prompt <内容>` - 自定义系统提示词
• `/reset_prompt` - 恢复默认系统提示词

**📄 文件生成命令（支持时间范围：1d/2d/1w）：**
• `/file-html [时间] <描述>` - 自由生成HTML文件
• `/file-html-daily [时间]` - 生成群聊摘要报告
• `/file-html-meeting [时间]` - 生成会议纪要
  示例: `/file-html-daily 1w` (最近1周)
        `/file-html 2d 总结最近两天的讨论`

**📁 文件上下文管理：**
• `/reset` - 彻底重置所有对话历史和上下文
• `/new` - 清除文件叠加态，开始新话题
• Quote文件消息 - 明确引用特定文件
• 自动上下文：文件上传后10分钟内自动使用

**💻 代码库分析：**
• `/codebase <gitlab_url>` - 设置代码库上下文
• 之后可直接提问代码相关问题
• 发送截图也可自动分析代码问题

**📝 文件分析能力：**
• Gemini：✅ 支持大文件原生分析（PDF等）
• ChatGPT：❌ 仅支持图片和文本对话
• Grok：❌ 仅支持图片和文本对话

**💡 使用技巧：**
1. 发送文件后10分钟内无需重复引用
2. 使用 /new 切换话题，避免文件干扰
3. 超过10分钟需重新发送或Quote文件
4. 自定义 Prompt 可让AI扮演特定角色
5. 审查代码: 发送 GitLab Commit URL

有问题随时使用 /help 查看本帮助！"""
        return {"content": help_text}
    
    elif command == "show_prompt":
        # Show current prompt
        custom_prompt = context_manager.get_custom_prompt(chat_id, bot_type)
        if custom_prompt:
            response = f"📝 当前使用的自定义 Prompt:\n\n{custom_prompt}\n\n💡 使用 /reset_prompt 可以恢复默认设置"
        else:
            default_prompt = BOT_CONFIGS[bot_type]["system_prompt"]
            response = f"📝 当前使用默认 Prompt:\n\n{default_prompt}\n\n💡 使用 /set_prompt <内容> 可以自定义\n💡 使用 /reset_prompt 可以恢复默认（如果已自定义）"
        return {"content": response}
    
    elif command == "set_prompt":
        # Set custom prompt
        if not args or len(args.strip()) < 10:
            return {"content": "❌ 请提供有效的 prompt 内容\n\n用法：/set_prompt 你是一个专业的Python开发专家..."}
        
        if len(args) > 2000:
            return {"content": "❌ Prompt 内容过长，请限制在 2000 字符以内"}
        
        success = context_manager.set_custom_prompt(chat_id, user_id, bot_type, args.strip())
        if success:
            response = f"✅ 已设置自定义 Prompt\n\n预览:\n{args.strip()[:200]}{'...' if len(args) > 200 else ''}\n\n💡 使用 /show_prompt 查看完整内容"
        else:
            response = "❌ 设置失败，请稍后重试"
        return {"content": response}
    
    elif command == "reset_prompt":
        # Reset to default prompt
        success = context_manager.delete_custom_prompt(chat_id, bot_type)
        default_prompt = BOT_CONFIGS[bot_type]["system_prompt"]
        if success:
            response = f"✅ 已恢复默认 Prompt\n\n{default_prompt[:200]}{'...' if len(default_prompt) > 200 else ''}"
        else:
            response = "❌ 重置失败，或当前已在使用默认 Prompt"
        return {"content": response}
    
    elif command == "new":
        # Clear file context and start new conversation
        try:
            # Clear file contexts for this chat
            success = context_manager.clear_file_context(chat_id)
            if success:
                response = "✅ 已清除文件上下文，开始新对话\n\n💡 之前的文件将不再自动使用，如需引用请重新发送或 Quote"
            else:
                response = "✅ 已清除上下文\n\n💡 当前没有活跃的文件上下文"
        except Exception as e:
            logger.error(f"[PROMPT_CMD] Failed to clear context: {e}")
            response = "❌ 清除失败，请稍后重试"
        return {"content": response}
    
    elif command == "reset":
        # Completely clear all chat metrics and history via timestamp reset
        try:
            now_iso = datetime.now().isoformat()
            
            # 1. Set context start timestamp in DB (Per Session isolation)
            success = context_manager.set_context_start(
                chat_id=chat_id,
                bot_type=bot_type,
                user_id=user_id,
                timestamp=now_iso
            )
            # 2. Note: Disabling destructive clear_file_context(chat_id) 
            # to preserve history and maintain per-bot isolation as per audit.
            # File context is now filtered by bot_type and timestamp in lookup.
            pass
            
            # 3. Clear project context if any
            # Note: We keep this per-chat for now as project context is shared in group
            if chat_id in _user_project_context:
                del _user_project_context[chat_id]
            
            if success:
                response = (
                    f"✅ 已重置 {bot_type} 的对话上下文\n\n"
                    f"💡 历史记录已保留但不再被引用。\n"
                    f"📌 现在是一个全新的开始！"
                )
                if args.strip():
                    # Combined command: reset + question
                    return {
                        "content": response + "\n\n---\n\n",
                        "continue_with_question": args.strip()
                    }
            else:
                response = "❌ 重置失败，请稍后重试"
        except Exception as e:
            logger.error(f"[PROMPT_CMD] Failed to reset context: {e}")
            response = "❌ 重置失败，请稍后重试"
        return {"content": response}
    
    elif command == "codebase":
        # Set GitLab project context for Codebase QA
        # Supports: /codebase <url> [optional question]
        if not args.strip():
            response = (
                "❌ 用法: `/codebase <gitlab_url> [问题]`\n\n"
                "示例:\n"
                "- `/codebase https://gitlab.example.com/team/myproject`\n"
                "- `/codebase https://gitlab.example.com/team/myproject 登录功能在哪里？`"
            )
            return {"content": response}
        
        # Parse args: first part is URL/path or NICKNAME, rest is optional question
        args_parts = args.strip().split(maxsplit=1)
        project_input = args_parts[0]
        inline_question = args_parts[1] if len(args_parts) > 1 else None
        
        project_path = project_input
        branch = "main"
        gitlab_base_url = os.getenv("GITLAB_URL", "http://gitlab.goldenstand.com")

        # Check for nickname first
        if project_input.lower() in PROJECT_NICKNAMES:
            config = PROJECT_NICKNAMES[project_input.lower()]
            project_path = config["project_path"]
            gitlab_base_url = config["gitlab_url"]
            branch = config["branch"]
            print(f"[CODEBASE_CMD] Using nickname {project_input} -> {project_path} ({branch})", flush=True)
            logger.info(f"[CODEBASE_CMD] Using nickname {project_input} -> {project_path} ({branch})")
        else:
            print(f"[CODEBASE_CMD] Parsing as URL: {project_input}", flush=True)
            # Check if it's a URL and extract project path + branch
            # Pattern for tree view: /-/tree/branch_name
            # Pattern for blob view: /-/blob/branch_name/file_path
            url_match = re.match(r"https?://[^\s/]+/(.+?)(?:/-/.*)?$", project_input)
            if url_match:
                project_path = url_match.group(1)
                
                # Handle branch extraction from /-/tree/ or /-/blob/
                if "/-/tree/" in project_input:
                    # Format: domain/project/-/tree/branch
                    parts = project_input.split("/-/tree/")
                    project_path = url_match.group(1).split("/-/tree/")[0]
                    branch = parts[1].split("/")[0] if len(parts) > 1 else "main"
                elif "/-/blob/" in project_input:
                    # Format: domain/project/-/blob/branch/file
                    parts = project_input.split("/-/blob/")
                    project_path = url_match.group(1).split("/-/blob/")[0]
                    branch = parts[1].split("/")[0] if len(parts) > 1 else "main"
                elif "/-/" in project_path:
                    project_path = project_path.split("/-/")[0]

            # Extract GitLab base URL from input
            gitlab_url_match = re.match(r"(https?://[^/]+)", project_input)
            gitlab_base_url = gitlab_url_match.group(1) if gitlab_url_match else os.getenv("GITLAB_URL", "https://gitlab.goldenstand.com")

        
        # Save project context with URL and branch
        _user_project_context[chat_id] = {
            "project_path": project_path,
            "gitlab_url": gitlab_base_url,
            "branch": branch
        }
        
        logger.info(f"[CODEBASE_CMD] Set project context for {chat_id}: {project_path} (branch: {branch}) @ {gitlab_base_url}")
        
        # If there's an inline question, return it for further processing
        if inline_question:
            return {
                "content": f"🔍 正在分析 `{project_path}` 代码库 (分支: `{branch}`)...",
                "continue_with_question": inline_question,
                "project_path": project_path,
                "branch": branch
            }
        
        # No question, just confirm context set
        response = (
            f"✅ 已设置代码库上下文: `{project_path}`\n"
            f"📌 当前分支: `{branch}`\n\n"
            f"现在你可以直接提问，例如:\n"
            f"- \"这些表名在哪些文件中出现过？\"\n"
            f"- \"creditor_code 字段是在哪里处理的？\"\n"
            f"- \"项目的原始权益人判断逻辑在哪里？\"\n\n"
            f"_提示: 发送截图也可以分析代码问题_"
        )
        return {"content": response}
    
    elif command == "file-html":
        # File generation mode - NOT a terminal command
        # Pass through to normal LLM flow with file output flag
        # Supports time range: /file-html [1d|2d|1w] <description>
        import re
        time_range = "last_24h"  # Default
        user_request = args.strip() if args else ""
        
        # Check if first arg is a time range pattern
        if args:
            parts = args.strip().split(maxsplit=1)
            if parts and re.match(r"^\d+[dwh]$", parts[0].lower()):
                time_range = parts[0].lower()
                user_request = parts[1] if len(parts) > 1 else ""
                logger.info(f"[FILE_CMD] /file-html detected time range: {time_range}")
        
        if not user_request or len(user_request.strip()) < 2:
            return {"content": "❌ 请提供生成需求\n\n用法：/file-html 制作一个登录页面\n      /file-html 1w 总结本周的对话"}
        
        return {
            "file_output_mode": True,
            "user_request": user_request.strip(),
            "continue_with_llm": True,
            "template_name": None,  # Free-form HTML
            "date_range": time_range,
        }
    
    elif command == "file-html-daily":
        # Daily summary report template
        # LLM outputs structured JSON, rendered via daily_report.html template
        # Supports time range: /file-html-daily [2d|3d|1w] [custom prompt]
        import re
        time_range = "last_24h"  # Default
        user_prompt = args.strip() if args and args.strip() else "请根据群聊记录生成一份摘要报告"
        
        # Check if first arg is a time range pattern (e.g., 2d, 1w, 3d)
        if args:
            parts = args.strip().split(maxsplit=1)
            if parts and re.match(r"^\d+[dwh]$", parts[0].lower()):
                time_range = parts[0].lower()
                user_prompt = parts[1] if len(parts) > 1 else "请根据群聊记录生成一份摘要报告"
                logger.info(f"[FILE_CMD] Detected time range: {time_range}")
        
        return {
            "file_output_mode": True,
            "user_request": user_prompt,
            "continue_with_llm": True,
            "template_name": "daily",  # Use daily_report.html template
            "date_range": time_range,  # Pass time range to archive query
        }
    
    elif command == "file-html-meeting":
        # Meeting notes template
        # LLM outputs structured JSON, rendered via meeting_notes.html template
        # Supports time range: /file-html-meeting [1d|2d|1w] [custom prompt]
        import re
        time_range = "last_24h"  # Default
        user_prompt = args.strip() if args and args.strip() else "请根据群聊内容整理一份会议纪要"
        
        # Check if first arg is a time range pattern
        if args:
            parts = args.strip().split(maxsplit=1)
            if parts and re.match(r"^\d+[dwh]$", parts[0].lower()):
                time_range = parts[0].lower()
                user_prompt = parts[1] if len(parts) > 1 else "请根据群聊内容整理一份会议纪要"
                logger.info(f"[FILE_CMD] /file-html-meeting detected time range: {time_range}")
        
        return {
            "file_output_mode": True,
            "user_request": user_prompt,
            "continue_with_llm": True,
            "template_name": "meeting",  # Use meeting_notes.html template
            "date_range": time_range,
        }
    
    return None



def _extract_urls(text: str) -> list[str]:
    """Extract all URLs from text.
    
    Args:
        text: Input text to search for URLs
        
    Returns:
        List of URLs found in text
    """
    url_pattern = r'https?://[^\s<>"{}|\^`\[\]]+'
    return re.findall(url_pattern, text)


async def _fetch_url_content(url: str) -> str | None:
    """Fetch content from URL asynchronously.
    
    Args:
        url: URL to fetch
        
    Returns:
        Text content from URL, or None if fetch failed
    """
    try:
        logger.info(f"[URL_FETCH] Fetching content from: {url}")
        
        # Fetch URL content in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.get(
                url, 
                timeout=10,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
        )
        
        if response.status_code == 200:
            # Try to extract text content
            content_type = response.headers.get('content-type', '')
            
            if 'text/html' in content_type:
                try:
                    from bs4 import BeautifulSoup
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Remove script, style, nav, footer, header tags
                    for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
                        element.decompose()
                    
                    # Try to find main content area
                    # Common article containers
                    main_content = None
                    for selector in ['article', 'main', '[role="main"]', '.post-content', '.article-content', '.entry-content']:
                        main_content = soup.select_one(selector)
                        if main_content:
                            break
                    
                    # If no specific article container found, use body
                    if not main_content:
                        main_content = soup.body or soup
                    
                    # Extract text
                    text = main_content.get_text(separator='\n', strip=True)
                    
                    # Clean up excessive whitespace
                    lines = [line.strip() for line in text.split('\n') if line.strip()]
                    content = '\n'.join(lines)
                    
                except ImportError:
                    # Fallback to simple extraction if BeautifulSoup not available
                    logger.warning("[URL_FETCH] BeautifulSoup not available, using simple extraction")
                    import html
                    text = response.text
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    content = html.unescape(text)
            else:
                # Plain text or other
                content = response.text
            
            logger.info(f"[URL_FETCH] Successfully fetched {len(content)} chars from {url}")
            return content[:20000]  # Increased limit to 20000 chars
        else:
            logger.warning(f"[URL_FETCH] HTTP {response.status_code} from {url}")
            return None
            
    except Exception as e:
        logger.error(f"[URL_FETCH] Failed to fetch {url}: {e}")
        return None


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
    file_output_mode: bool = False,
) -> None:
    """Call the appropriate LLM asynchronously and update task result."""
    print(f"[LLM_ASYNC_START] stream_id={stream_id} content={content[:50]!r}", flush=True)
    
    # Check for prompt management commands
    # Commands can appear after @mention, so search for / anywhere in content
    content_stripped = content.strip()
    # [FIX] Strict command detection: must be at start or immediately after a mention
    is_valid_command_start = False
    command_part = ""
    
    if content_stripped.startswith("/"):
        is_valid_command_start = True
        command_part = content_stripped
    elif content_stripped.startswith("@"):
        # Handle cases like "@bot /command" or "@bot/command"
        slash_idx = content_stripped.find("/")
        if slash_idx != -1:
            prefix = content_stripped[:slash_idx].strip()
            # If prefix is just the mention (no spaces before the slash)
            if prefix.startswith("@") and " " not in prefix:
                is_valid_command_start = True
                command_part = content_stripped[slash_idx:]
            # If prefix is like "@bot " and slash is at the start of the next word
            elif prefix.startswith("@") and prefix.count("@") == 1:
                is_valid_command_start = True
                command_part = content_stripped[slash_idx:]

    if is_valid_command_start and command_part:
        try:
            parts = command_part.split(maxsplit=1)
            command = parts[0][1:]  # Remove leading /
            args = parts[1] if len(parts) > 1 else ""
            
            cmd_result = _handle_prompt_command(command, args, bot_type, chat_id, user_id)
            if cmd_result:
                # Check if command wants to continue with a question (e.g., /codebase url question)
                if cmd_result.get("continue_with_question"):
                    inline_question = cmd_result["continue_with_question"]
                    project_path = cmd_result["project_path"]
                    
                    # Update stream with initial status
                    if stream_id in _stream_tasks:
                        _stream_tasks[stream_id]["content"] = cmd_result["content"]
                    
                    # Trigger CodebaseQAFlow immediately
                    # Get gitlab_url from cached context (set by _handle_prompt_command)
                    cached_context = _user_project_context.get(chat_id)
                    gitlab_base_url = cached_context["gitlab_url"] if cached_context else os.getenv("GITLAB_URL", "https://gitlab.goldenstand.com")
                    gitlab_token = os.getenv("GITLAB_TOKEN")
                    
                    if gitlab_token:
                        try:
                            flow = CodebaseQAFlow(
                                gitlab_url=gitlab_base_url,
                                private_token=gitlab_token,
                                project_id=project_path,
                                query=inline_question,
                                branch=cmd_result.get("branch", "main")
                            )
                            
                            loop = asyncio.get_running_loop()
                            qa_result = await loop.run_in_executor(None, flow.kickoff)
                            
                            if stream_id in _stream_tasks:
                                _stream_tasks[stream_id]["content"] = str(qa_result)
                                _stream_tasks[stream_id]["finished"] = True
                                _stream_tasks[stream_id]["completed_at"] = time.time()
                            
                            # Add to context
                            get_context_manager().add_message(
                                chat_id=chat_id,
                                sender_id=f"bot_{bot_type}_qa",
                                sender_name=f"{bot_type} QA",
                                content=str(qa_result),
                                role="assistant",
                                bot_type=bot_type,
                            )
                            
                            logger.info(f"[CODEBASE_CMD] Completed inline QA for {chat_id}")
                            return
                            
                        except Exception as e:
                            logger.error(f"[CODEBASE_CMD] Inline QA failed: {e}")
                            if stream_id in _stream_tasks:
                                _stream_tasks[stream_id]["content"] = f"❌ 代码分析失败: {e}"
                                _stream_tasks[stream_id]["finished"] = True
                                _stream_tasks[stream_id]["completed_at"] = time.time()
                            return
                    else:
                        if stream_id in _stream_tasks:
                            _stream_tasks[stream_id]["content"] = "❌ GITLAB_TOKEN 未配置"
                            _stream_tasks[stream_id]["finished"] = True
                            _stream_tasks[stream_id]["completed_at"] = time.time()
                        return
                
                # Check if command wants to continue with LLM (e.g., /file-html, /file-html-daily)
                if cmd_result.get("continue_with_llm"):
                    # File output mode - continue to normal LLM flow
                    file_output_mode = cmd_result.get("file_output_mode", False)
                    template_name = cmd_result.get("template_name")  # None for free-form, "daily" or "meeting" for templates
                    date_range = cmd_result.get("date_range", "last_24h")  # Time range for archive query
                    # Replace content with user's actual request (remove /file-html prefix)
                    content = cmd_result.get("user_request", content)
                    logger.info(f"[FILE_OUTPUT] Continuing to LLM with file_output_mode={file_output_mode}, template={template_name}, date_range={date_range}")
                    # Fall through to normal LLM processing below
                elif cmd_result.get("continue_with_question"):
                    # [FIX] Combined command (e.g., /reset question)
                    logger.info(f"[CMD_FLOW] Command /{command} continuing with question: {cmd_result['continue_with_question'][:50]}...")
                    # Prepend command response (e.g., "Reset complete") to the stream
                    if stream_id in _stream_tasks:
                        _stream_tasks[stream_id]["content"] = cmd_result["content"]
                    
                    # Override content for the LLM call and fall through
                    content = cmd_result["continue_with_question"]
                    
                    # [NEW] Re-add to context after reset to ensure it's in the DB with a newer timestamp
                    # so that get_messages_for_llm (which filters by reset_ts) will pick it up.
                    context_manager.add_message(
                        chat_id=chat_id,
                        sender_id=user_id,
                        sender_name=user_name or user_id,
                        content=content,
                        role="user",
                        wecom_msg_id=f"reset_{wecom_msg_id}" if wecom_msg_id else None,
                        bot_type=bot_type,
                    )
                else:
                    # Generic command response (e.g., /help, /show_prompt)
                    # Update status and finish
                    if stream_id in _stream_tasks:
                        _stream_tasks[stream_id]["content"] = cmd_result.get("content", "指令已执行")
                        _stream_tasks[stream_id]["finished"] = True
                        _stream_tasks[stream_id]["completed_at"] = time.time()
                    
                    logger.info(f"[PROMPT_CMD] Handled command /{command} for {bot_type} in {chat_id}")
                    return
        except Exception as e:
            logger.exception(f"[AIBOT_CMD_ERR] Failed to process command: {e}")
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = f"❌ 指令执行异常: {e}"
                _stream_tasks[stream_id]["finished"] = True
                _stream_tasks[stream_id]["completed_at"] = time.time()
            return
    
    # Initialize file_output_mode and template_name if not set by command handling above
    try:
        file_output_mode
    except NameError:
        file_output_mode = False
    
    try:
        template_name
    except NameError:
        template_name = None
    
    try:
        date_range
    except NameError:
        date_range = "last_24h"

    # Check for GitLab Code Review Request
    # Pattern: https://<any-domain>/<path>/-/commit/<sha>
    # Accepts: gitlab.*, git.*, or any domain with /-/commit/ structure
    # SHA can be 7-40 characters, case-insensitive
    gitlab_pattern = r"(https?://)([^\s/]+)/([^\s]+)/-/commit/([a-fA-F0-9]{7,40})"
    gitlab_match = re.search(gitlab_pattern, content_stripped, re.IGNORECASE)
    
    # Trigger if URL found and content contains "review" or "审查", or if it's JUST the URL
    # But NOT if negative keywords are present
    has_positive_keyword = (
        "review" in content_stripped.lower() 
        or "审查" in content_stripped
        or "审核" in content_stripped
        or "检查" in content_stripped
        or "看看" in content_stripped
        or "帮我看" in content_stripped
    )
    has_negative_keyword = (
        "不要审查" in content_stripped
        or "别审查" in content_stripped
        or "不用审查" in content_stripped
        or "don't review" in content_stripped.lower()
        or "no review" in content_stripped.lower()
    )
    is_url_only = len(content_stripped) == len(gitlab_match.group(0)) if gitlab_match else False
    
    is_review_request = gitlab_match and (
        (has_positive_keyword and not has_negative_keyword)
        or is_url_only
    )
    
    if is_review_request:
        try:
            protocol = gitlab_match.group(1)
            domain = gitlab_match.group(2)
            project_path = gitlab_match.group(3)
            commit_sha = gitlab_match.group(4)
            gitlab_base_url = f"{protocol}{domain}"
            
            logger.info(f"[GITLAB_REVIEW] Detected review request: {gitlab_base_url} {project_path} {commit_sha}")
            
            # Save project context for future QA (including the GitLab host)
            _user_project_context[chat_id] = {
                "project_path": project_path,
                "gitlab_url": gitlab_base_url
            }
            
            # Update status to "Reviewing"
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = "🔍 正在进行多Agent代码审查，请稍候...\n(架构/性能/测试专家正在分析)"
            
            # Get token from env
            gitlab_token = os.getenv("GITLAB_TOKEN")
            if not gitlab_token:
                raise ValueError("GITLAB_TOKEN environment variable not set")
            
            # Run Flow
            flow = CodeReviewFlow(
                gitlab_url=gitlab_base_url,
                private_token=gitlab_token,
                project_id=project_path,
                commit_sha=commit_sha
            )
            
            # Run in executor to avoid blocking asyncio loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, flow.kickoff)
            
            final_response = f"✅ 代码审查完成\n\n{result}"
            
            # Update task
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = final_response
                _stream_tasks[stream_id]["finished"] = True
                _stream_tasks[stream_id]["completed_at"] = time.time()
                
            return
            
        except Exception as e:
            logger.error(f"[GITLAB_REVIEW] Error during review: {e}")
            error_msg = f"❌ 代码审查失败: {str(e)}"
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = error_msg
                _stream_tasks[stream_id]["finished"] = True
                _stream_tasks[stream_id]["error"] = True
                _stream_tasks[stream_id]["error"] = True
            return

    
    try:
        config = BOT_CONFIGS[bot_type]
        provider = config["provider"]
        
        # Prompt priority: Custom > Default
        context_manager = get_context_manager()
        custom_prompt = context_manager.get_custom_prompt(chat_id, bot_type)
        if custom_prompt:
            system_prompt = custom_prompt
            logger.info(f"[PROMPT] Using custom prompt for {bot_type} in {chat_id}")
        else:
            system_prompt = config["system_prompt"]
            logger.info(f"[PROMPT] Using default prompt for {bot_type}")


        # If file_output_mode, append file generation instruction to system prompt
        if file_output_mode:
            if template_name == "daily":
                # Daily summary template - LLM outputs structured JSON
                file_instruction = (
                    "\n\n[重要：JSON结构化输出模式 - 每日摘要报告]\n"
                    "请分析群聊内容并输出以下JSON格式（不要包含其他内容）：\n"
                    "```json\n"
                    "{\n"
                    '  "topics": [\n'
                    '    {"title": "讨论主题", "summary": "详细摘要", "sentiment": "positive/neutral/negative"}\n'
                    "  ],\n"
                    '  "todos": [\n'
                    '    {"task": "待办事项", "assignee": "@负责人"}\n'
                    "  ],\n"
                    '  "insights": ["关键见解1", "关键见解2"],\n'
                    '  "participant_count": 5\n'
                    "}\n"
                    "```\n"
                    "必须输出有效的JSON，不要添加任何解释或markdown代码块之外的内容。"
                )
                logger.info(f"[FILE_OUTPUT] Added daily template JSON schema to system prompt")
            elif template_name == "meeting":
                # Meeting notes template - LLM outputs structured JSON
                file_instruction = (
                    "\n\n[重要：JSON结构化输出模式 - 会议纪要]\n"
                    "请分析群聊内容并输出以下JSON格式（不要包含其他内容）：\n"
                    "```json\n"
                    "{\n"
                    '  "title": "会议主题",\n'
                    '  "attendees": ["张三", "李四", "王五"],\n'
                    '  "agenda": [\n'
                    '    {"item": "议程项目", "discussion": "讨论内容", "decisions": ["决定1"]}\n'
                    "  ],\n"
                    '  "action_items": [\n'
                    '    {"task": "行动项", "owner": "负责人", "due": "截止日期"}\n'
                    "  ],\n"
                    '  "next_meeting": "下次会议时间"\n'
                    "}\n"
                    "```\n"
                    "必须输出有效的JSON，不要添加任何解释或markdown代码块之外的内容。"
                )
                logger.info(f"[FILE_OUTPUT] Added meeting template JSON schema to system prompt")
            else:
                # Free-form HTML mode (template_name is None)
                file_instruction = (
                    "\n\n[CRITICAL SYSTEM REQUIREMENT: FILE OUTPUT MODE]\n"
                    "The user explicitly requested an HTML file. You MUST follow this structure REGARDLESS of your adopted persona or style:\n"
                    "1. SUMMARY: A single sentence (max 50 chars) describing your generation.\n"
                    "2. CONTENT: The complete HTML content wrapped inside <FILE name=\"output.html\">...</FILE> tags.\n"
                    "3. STYLING: Use Tailwind CSS CDN for all styling.\n"
                    "Failure to use the <FILE> tags will break the system integration. This is a mandatory technical requirement.\n\n"
                    "Example Output:\n"
                    "生成了一份风格前卫的分析报告。\n"
                    "<FILE name=\"report.html\"><html>...</html></FILE>"
                )
                logger.info(f"[FILE_OUTPUT] Added highly authoritative free-form HTML instruction to system prompt")
            system_prompt = system_prompt + file_instruction

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

        # Detect and fetch URL content if present
        urls = _extract_urls(content)

        # Phase 2: Archive Context Injection for ALL file commands
        archive_context = ""
        is_report_request = False
        if file_output_mode:
            logger.info(f"[AIBOT_FILE] Injecting archive context for file command, date_range={date_range}")
            is_report_request = True  # Mark as report to enable template auto-conversion
            # Fetch archived messages for the specified time range
            history = get_merged_chat_history(chat_id, date=date_range, limit=500)
            if history:
                archive_context = _format_chat_history(history)
                logger.info(f"[AIBOT_CTX] Injected {len(history)} messages from archive ({date_range} window)")
            else:
                logger.warning(f"[AIBOT_CTX] No history found for {date_range} in chat={chat_id}")

        url_contents = []
        if urls:
            logger.info(f"[URL_DETECT] Found {len(urls)} URL(s) in message")
            for url in urls[:3]:  # Limit to first 3 URLs to avoid overload
                url_content = await _fetch_url_content(url)
                if url_content:
                    url_contents.append({
                        "url": url,
                        "content": url_content[:8000]  # Limit to 8000 chars per URL
                    })
        
        # Get conversation history
        messages = context_manager.get_messages_for_llm(
            chat_id,
            system_prompt=system_prompt,
            bot_type=bot_type,
        )
        
        # If URLs were fetched, prepend their content to the user's message context
        if url_contents:
            url_context = "\n\n---\n\n".join([
                f"**网页内容来自 {uc['url']}:**\n\n{uc['content']}" 
                for uc in url_contents
            ])
            # Prepend URL content to the latest user message
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] = f"{url_context}\n\n---\n\n用户问题：{messages[-1]['content']}"
                logger.info(f"[URL_CTX] Added {len(url_contents)} URL(s) content to context")

        # Inject Archive Context if available
        if archive_context and messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = (
                f"### 今日群聊记录摘要 (仅供参考):\n\n{archive_context}\n\n"
                f"---\n\n基于以上对话背景，请按照要求执行：{messages[-1]['content']}"
            )

        # 1. Quoted File (Specific)
        file_ctx = None
        if quoted_msg_id:
            # Try original ID first
            file_ctx = context_manager.get_active_file(chat_id, wecom_msg_id=quoted_msg_id, bot_type=bot_type)
            if not file_ctx:
                # Fallback: try derived image ID (file_{id}) to maintain vision quote matching
                file_ctx = context_manager.get_active_file(chat_id, wecom_msg_id=f"file_{quoted_msg_id}", bot_type=bot_type)
            
            if file_ctx:
                logger.info(f"[AIBOT_CTX] Found quoted file by MsgId: {file_ctx['filename']}")
        
        if not file_ctx and quoted_filename:
             file_ctx = context_manager.get_active_file(chat_id, filename=quoted_filename, bot_type=bot_type)
             if file_ctx:
                 logger.info(f"[AIBOT_CTX] Found quoted file by Filename: {file_ctx['filename']}")

        # 2. Latest File (Sticky/Global) - with 10-minute time window
        if not file_ctx:
             file_ctx = context_manager.get_active_file(chat_id, limit=50, bot_type=bot_type)
             
             # Check if file is within 10-minute window
             if file_ctx:
                file_timestamp = file_ctx.get("timestamp", 0)
                elapsed_minutes = (time.time() - file_timestamp) / 60
                
                if elapsed_minutes > 10:
                    logger.info(f"[AIBOT_CTX] File expired (age: {elapsed_minutes:.1f}min > 10min), ignoring sticky context")
                    file_ctx = None  # Expired, don't use

        use_file_context = False
        if file_ctx:
            # Check if provider supports file analysis
            supports_files = config.get("supports_file_analysis", False)
            
            if supports_files:
                use_file_context = True
                logger.info(f"[AIBOT_CTX] Found file context for chat={chat_id}: {file_ctx['filename']} (UCS={not (file_ctx['uri'].startswith('content:') or file_ctx['uri'].startswith('base64:'))})")
            else:
                logger.info(
                    f"[AIBOT_CTX] Skipping file context - {bot_type} does not support "
                    f"native file analysis (file: {file_ctx['filename']})"
                )
                file_ctx = None  # Clear it, don't use

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
                    
                    # Fetch limited history for file analysis to avoid hallucinating old results
                    context = context_manager.get_context(chat_id, bot_type=bot_type)
                    limited_messages = context.messages[-5:] if len(context.messages) > 5 else context.messages
                    
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    for msg in limited_messages:
                        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                    messages.append({"role": "user", "content": messages_for_llm[-1]["content"] if messages_for_llm else ""})

                    response = await loop.run_in_executor(
                        None,
                        lambda: router.chat_with_file(
                            provider=provider,
                            text=messages[-1]["content"],
                            file_data=file_bytes,
                            file_mime_type=file_ctx["mime"],
                            filename=filename,
                            history=messages[:-1],
                            system_prompt=system_prompt,
                            max_tokens=4096,
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
                                text=messages[-1]["content"],
                                file_data=None, 
                                file_mime_type=file_ctx["mime"],
                                filename=filename,
                                file_uri=file_uri,
                                history=messages[:-1],
                                system_prompt=system_prompt,
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
                                    text=messages[-1]["content"],
                                    file_data=file_bytes, 
                                    file_mime_type=file_ctx["mime"],
                                    filename=filename,
                                    history=messages[:-1],
                                    system_prompt=system_prompt,
                                    max_tokens=4096,
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
            response_url=response_url,
            file_only_mode=file_output_mode,
            is_report_request=is_report_request,
            template_name=template_name,
            raw_context=archive_context,
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
        print(f"--- [AIBOT_ENTRY] bot={bot_type} signature={msg_signature[:10]}... timestamp={timestamp} ---", flush=True)
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
    print(f"[AIBOT_TEXT_START] bot={bot_type} data_keys={list(data.keys())}", flush=True)
    # Cleanup old tasks on each message to prevent unbounded growth
    _cleanup_old_tasks()

    text_data = data.get("text", {})
    content = _sanitize_text(text_data.get("content", "").strip())

    # Extract user info
    from_data = data.get("from", {})
    user_id = from_data.get("user_id", from_data.get("userid", "unknown"))
    user_name = from_data.get("name", from_data.get("alias", user_id))

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

    is_report_request = False # Initialize for scope safety

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
            is_report_request=is_report_request,
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
    is_report_request: bool = False,
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

        # Fetch limited history (last 5 messages) for vision LLM call to prevent history-based hallucinations
        context = context_manager.get_context(chat_id, bot_type=bot_type)
        limited_messages = context.messages[-5:] if len(context.messages) > 5 else context.messages
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for msg in limited_messages:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": prompt})

        # Run vision LLM call in thread pool
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: router.chat_with_image(
                provider=provider,
                text=prompt,
                image_base64=image_base64,
                system_prompt=system_prompt,
                history=messages[:-1],
                max_tokens=4096,
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
            response_url=response_url,
            is_report_request=is_report_request,
            template_name=None,  # Vision flow doesn't use templates
            raw_context=None,
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
    file_output_mode = False

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
    
    # Detect report intent for file flow (check filename AND message content/caption)
    text_ctx = f"{filename} {data.get('content', '')}"
    is_report_request = _detect_daily_report_intent(text_ctx)
    
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
            is_report_request=is_report_request,
            system_prompt=config["system_prompt"],
            user_id=user_id,
            chat_id=chat_id,
            wecom_msg_id=wecom_msg_id,
            quoted_msg_id=quoted_msg_id,
            response_url=response_url,
            file_output_mode=file_output_mode,
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
    file_output_mode: bool = False,
    is_report_request: bool = False,
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
                sender_id=user_id,
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
            real_file_data = file_bytes
            real_file_uri = file_uri
            
            # Fetch limited history (last 5 messages) for file LLM call
            from src.crewai_enterprise.utils.chat_context import get_context_manager
            ctx_mgr = get_context_manager()
            context = ctx_mgr.get_context(chat_id, bot_type=bot_type)
            limited_messages = context.messages[-5:] if len(context.messages) > 5 else context.messages
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            for msg in limited_messages:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            messages.append({"role": "user", "content": prompt})
            
            response = await loop.run_in_executor(
                None,
                lambda: router.chat_with_file(
                    provider=provider,
                    text=messages[-1]["content"],
                    file_data=real_file_data,
                    file_uri=real_file_uri,
                    file_mime_type=mime_type,
                    filename=filename,
                    history=messages[:-1],
                    system_prompt=system_prompt,
                    max_tokens=4096,
                )
            )

        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        # Post-process response for generated files (Auditor Refinement)
        final_content = await _process_llm_file_output(
            bot_type=bot_type,
            chat_id=chat_id,
            content=response.content,
            user_id=user_id,
            user_name=None,  # user_name not in scope here
            response_url=response_url,
            is_report_request=is_report_request,
            template_name=None,  # File flow doesn't use templates
            raw_context=None,
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
