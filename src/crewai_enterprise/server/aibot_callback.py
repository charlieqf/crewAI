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
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from src.crewai_enterprise.utils.llm_router import LLMError, get_router
from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.storage_manager import get_storage_manager
from src.crewai_enterprise.utils.report_generator import generate_html_report
from src.crewai_enterprise.tools.archive.archive_tool import get_merged_chat_history
from src.crewai_enterprise.flows.code_review_flow import CodeReviewFlow
from src.crewai_enterprise.flows.codebase_qa_flow import CodebaseQAFlow
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
    _sanitize_text,
    _stream_tasks,
    _user_project_context,
    _detect_daily_report_intent,
    _format_chat_history,
    _handle_prompt_command,
    _upload_image_to_ucs,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


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
                        _stream_tasks[stream_id]["content"] = cmd_result.get("content", "命令已执行")
                        _stream_tasks[stream_id]["finished"] = True
                        _stream_tasks[stream_id]["completed_at"] = time.time()
                    
                    logger.info(f"[PROMPT_CMD] Handled command /{command} for {bot_type} in {chat_id}")
                    return
        except Exception as e:
            logger.exception(f"[AIBOT_CMD_ERR] Failed to process command: {e}")
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = f"❌ 命令执行异常: {e}"
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
        or "审查" in content_stripped
        or "横竖" in content_stripped
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
                _stream_tasks[stream_id]["content"] = "🔄 正在运行中：Agent代码审查，请稍候...\n(架构/总能力/测试专家正在分析)"
            
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
                    "\n\n[重要：JSON结构包含输出模式 - 每需要摘要报告]\n"
                    "请分析群聊内容并输出以下JSON格式（不要包含其他内容）：\n"
                    "```json\n"
                    "{\n"
                    '  "topics": [\n'
                    '    {"title": "讨论主题", "summary": "详细摘要", "sentiment": "positive/neutral/negative"}\n'
                    "  ],\n"
                    '  "todos": [\n'
                    '    {"task": "获取待办项", "assignee": "@责任人"}\n'
                    "  ],\n"
                    '  "insights": ["相关洞察点1", "相关洞察点2"],\n'
                    '  "participant_count": 5\n'
                    "}\n"
                    "```\n"
                    "必须输出有效的JSON，不要添加任何点缀或markdown代码块之外的内容。"
                )
                logger.info(f"[FILE_OUTPUT] Added daily template JSON schema to system prompt")
            elif template_name == "meeting":
                # Meeting notes template - LLM outputs structured JSON
                file_instruction = (
                    "\n\n[重要：JSON结构包含输出模式 - 会议纪要]\n"
                    "请分析群聊内容并输出以下JSON格式（不要包含其他内容）：\n"
                    "```json\n"
                    "{\n"
                    '  "title": "会议主题",\n'
                    '  "attendees": ["张三", "李四", "王五"],\n'
                    '  "agenda": [\n'
                    '    {"item": "议程项目", "discussion": "讨论内容", "decisions": ["决定1"]}\n'
                    "  ],\n"
                    '  "action_items": [\n'
                    '    {"task": "行动项", "owner": "责任人", "due": "待定期限"}\n'
                    "  ],\n"
                    '  "next_meeting": "下次会议时间"\n'
                    "}\n"
                    "```\n"
                    "必须输出有效的JSON，不要添加任何点缀或markdown代码块之外的内容。"
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
                    "生成了一份风格简洁的分析报告。\n"
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
                f"**网页内容摘要自 {uc['url']}:**\n\n{uc['content']}" 
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
                f"---\n\n基于以上对话内容，请根据要求执行：{messages[-1]['content']}"
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
                    [f"{'用户' if m['role']=='user' else '模块'}: {m['content']}" for m in messages]
                )
                
                # Check if file context is inline text or cloud URI
                file_uri = file_ctx["uri"]
                filename = file_ctx["filename"]
                
                if file_uri and file_uri.startswith("content:"):
                    # Inline Text Context
                    raw_content = file_uri[8:]
                    full_prompt = (
                        f"对话历史:\n{history_text}\n\n"
                        f"（提示：用户之前上传了文件 {filename}，内容如下，请基于文件内容回答）：\n"
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
                    full_prompt = f"对话历史:\n{history_text}\n\n（提示：用户之前上传了文件 {filename}，请基于文件内容回答）"
                    
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
                    
                    full_prompt = f"对话历史:\n{history_text}\n\n（提示：用户之前上传了文件 {filename}，请基于文件内容回答）"
                    
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
                context_error_hint = f"\n\n（提示：需补充历史图片/文件，本次回答仅基于纯文本记录。错误：{str(e)[:50]}...）"

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
        stream_json = _make_text_stream(stream_id, "任务已过期，请重新提问", finish=True)
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
        error_note = f"\n\n（提示：图片处理失败：{image_error}）" if image_error else ""
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
        response_text = f"收到你的图片，但处理时出现问题：{result}\n\n请稍后重试，或添加文字说明。"
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


