from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import urllib3

from src.crewai_enterprise.server.handlers.aibot.config import (
    BOT_CONFIGS,
    _stream_tasks,
    _user_project_context,
)
from src.crewai_enterprise.server.handlers.aibot.commands import (
    _detect_daily_report_intent,
    _handle_prompt_command,
)
from src.crewai_enterprise.server.handlers.aibot.file_output import _format_chat_history
from src.crewai_enterprise.server.handlers.aibot.quoted_media import (
    QuotedMediaError,
    is_media_quote,
    resolve_quoted_media,
)
from src.crewai_enterprise.server.handlers.aibot.sync_trigger import (
    ArchiveSyncError,
    trigger_archive_sync,
)
from src.crewai_enterprise.server.handlers.context_prefix import extract_context_prefix
from src.crewai_enterprise.utils.file_content_store import FileContentStore
from src.crewai_enterprise.utils.llm_router import LLMError, get_router
from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.storage_manager import get_storage_manager
from src.crewai_enterprise.utils.report_generator import generate_html_report
from src.crewai_enterprise.utils.wecom_context import (
    build_context_summary,
    build_context_transcript,
    fetch_wecom_chat_context,
)
from src.crewai_enterprise.tools.archive.archive_tool import get_merged_chat_history
from src.crewai_enterprise.flows.code_review_flow import CodeReviewFlow
from src.crewai_enterprise.flows.codebase_qa_flow import CodebaseQAFlow

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


def _build_wecom_context_block(chat_id: str, window: int) -> str | None:
    if not chat_id or not window:
        return None
    end_dt = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
    start_dt = end_dt - timedelta(seconds=window)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    try:
        messages, truncated = fetch_wecom_chat_context(chat_id, start_str, end_str)
    except Exception as exc:
        logger.warning("[AIBOT_CTX] WeCom context fetch failed: %s", exc)
        return None
    if not messages:
        return None
    transcript, transcript_truncated = build_context_transcript(messages)
    summary = build_context_summary(
        messages,
        start_str,
        end_str,
        truncated=truncated or transcript_truncated,
    )
    lines = [
        "SYSTEM CONTEXT (WeCom)",
        f"Timeframe: {summary['start']} to {summary['end']}",
        f"Messages: {summary['count']}",
    ]
    if summary.get("truncated"):
        lines.append("Truncated: yes")
    if summary.get("first"):
        lines.append(f"First: {summary['first']}")
    if summary.get("last"):
        lines.append(f"Last: {summary['last']}")
    if transcript:
        lines.append("TRANSCRIPT:")
        lines.append(transcript)
    lines.append("Use this context for background only.")
    return "\n".join(lines)


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
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            ),
        )

        if response.status_code == 200:
            # Try to extract text content
            content_type = response.headers.get("content-type", "")

            if "text/html" in content_type:
                try:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")

                    # Remove script, style, nav, footer, header tags
                    for element in soup(
                        [
                            "script",
                            "style",
                            "nav",
                            "footer",
                            "header",
                            "aside",
                            "iframe",
                        ]
                    ):
                        element.decompose()

                    # Try to find main content area
                    # Common article containers
                    main_content = None
                    for selector in [
                        "article",
                        "main",
                        '[role="main"]',
                        ".post-content",
                        ".article-content",
                        ".entry-content",
                    ]:
                        main_content = soup.select_one(selector)
                        if main_content:
                            break

                    # If no specific article container found, use body
                    if not main_content:
                        main_content = soup.body or soup

                    # Extract text
                    text = main_content.get_text(separator="\n", strip=True)

                    # Clean up excessive whitespace
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    content = "\n".join(lines)

                except ImportError:
                    # Fallback to simple extraction if BeautifulSoup not available
                    logger.warning(
                        "[URL_FETCH] BeautifulSoup not available, using simple extraction"
                    )
                    import html

                    text = response.text
                    text = re.sub(
                        r"<script[^>]*>.*?</script>",
                        "",
                        text,
                        flags=re.DOTALL | re.IGNORECASE,
                    )
                    text = re.sub(
                        r"<style[^>]*>.*?</style>",
                        "",
                        text,
                        flags=re.DOTALL | re.IGNORECASE,
                    )
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    content = html.unescape(text)
            else:
                # Plain text or other
                content = response.text

            logger.info(
                f"[URL_FETCH] Successfully fetched {len(content)} chars from {url}"
            )
            return content[:20000]  # Increased limit to 20000 chars
        else:
            logger.warning(f"[URL_FETCH] HTTP {response.status_code} from {url}")
            return None

    except Exception as e:
        logger.error(f"[URL_FETCH] Failed to fetch {url}: {e}")
        return None


def _sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal and remove weird characters."""
    import os

    # Only take the basename to prevent path traversal
    name = os.path.basename(name)
    # Remove any non-alphanumeric/dot/hyphen/underscore characters
    import re

    name = re.sub(r"[^\w\.\-\u4e00-\u9fa5]", "_", name)
    # Limit length
    if len(name) > 100:
        name = name[:90] + "_" + name[-9:]
    return name


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

            logger.info(
                f"[AIBOT_TEMPLATE] Rendering {template_name} template for chat={chat_id}"
            )
            html_report, success = generate_html_report(
                content, chat_id, template_name=template_name, raw_context=raw_context
            )

            if success:
                # Successfully converted JSON to HTML via template
                storage = get_storage_manager()
                filename_prefix = (
                    "daily_report" if template_name == "daily" else "meeting_notes"
                )
                report_filename = (
                    f"{filename_prefix}_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                )
                upload_res = storage.upload_file(
                    html_report.encode("utf-8"),
                    report_filename,
                    content_type="text/html",
                )
                logger.info(
                    f"[AIBOT_TEMPLATE] Uploaded {template_name} report to cloud: {upload_res.url}"
                )

                emoji = "📋" if template_name == "daily" else "📝"
                label = "每日群聊摘要报告" if template_name == "daily" else "会议纪要"

                # Generate content-specific description by parsing JSON
                try:
                    import json

                    clean_json = content.strip()
                    if "```json" in clean_json:
                        clean_json = (
                            clean_json.split("```json")[-1].split("```")[0].strip()
                        )
                    data = json.loads(clean_json)

                    if template_name == "daily":
                        topics_count = len(data.get("topics", []))
                        todos_count = len(data.get("todos", []))
                        desc = (
                            f"提取了{topics_count}个讨论话题和{todos_count}个待办事项"
                        )
                    else:
                        agenda_count = len(data.get("agenda", []))
                        actions_count = len(data.get("action_items", []))
                        desc = (
                            f"整理了{agenda_count}个议程项目和{actions_count}个行动项"
                        )
                except:
                    desc = "已生成"

                # Never echo raw JSON content - only return link with description
                return f"{emoji} {label}：{desc}\n📄 云端链接: {upload_res.url}"
            else:
                # Template rendering failed - return error HTML instead of falling back
                logger.warning(
                    f"[AIBOT_TEMPLATE] Template rendering failed for {template_name}, returning error report"
                )
                storage = get_storage_manager()
                report_filename = (
                    f"error_report_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                )
                upload_res = storage.upload_file(
                    html_report.encode(
                        "utf-8"
                    ),  # html_report contains error HTML from render_template
                    report_filename,
                    content_type="text/html",
                )
                return f"❌ 模板渲染失败，请检查输出格式：\n{upload_res.url}"
        except Exception as e:
            logger.error(
                f"[AIBOT_TEMPLATE] Failed to render {template_name} template: {e}"
            )
            # Return error message instead of falling back
            return f"❌ 生成报告时出错: {str(e)[:100]}..."

    # Legacy: Auto-conversion for daily report intent detection (backward compatibility)
    elif (
        is_report_request
        and "topics" in content
        and "todos" in content
        and "{" in content
    ):
        try:
            from datetime import timedelta, timezone

            BEIJING_TZ = timezone(timedelta(hours=8))
            now_bj = datetime.now(BEIJING_TZ)

            logger.info(
                f"[AIBOT_REPORT] Detected potential JSON report, converting to HTML for chat={chat_id}"
            )
            html_report, success = generate_html_report(
                content, chat_id, template_name="daily"
            )

            if success:
                # Successfully converted JSON report to HTML
                storage = get_storage_manager()
                report_filename = (
                    f"daily_report_{now_bj.strftime('%Y%m%d_%H%M%S')}.html"
                )
                upload_res = storage.upload_file(
                    html_report.encode("utf-8"),
                    report_filename,
                    content_type="text/html",
                )
                logger.info(
                    f"[AIBOT_REPORT] Uploaded generated report to cloud: {upload_res.url}"
                )

                # Generate content-specific description (same as template path)
                try:
                    import json

                    clean_json = content.strip()
                    if "```json" in clean_json:
                        clean_json = (
                            clean_json.split("```json")[-1].split("```")[0].strip()
                        )
                    data = json.loads(clean_json)
                    topics_count = len(data.get("topics", []))
                    todos_count = len(data.get("todos", []))
                    desc = f"提取了{topics_count}个讨论话题和{todos_count}个待办事项"
                except:
                    desc = "已生成"

                # Never echo raw JSON - consistent with template path
                return f"📋 每日群聊摘要报告：{desc}\n📄 云端链接: {upload_res.url}"
            else:
                logger.warning(
                    f"[AIBOT_REPORT] HTML conversion success=False for chat={chat_id}, bypassing auto-upload."
                )
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
            logger.info(
                f"[AIBOT_FILE] No <FILE> tags found in file_only_mode, initiating auto-wrap fallback for chat={chat_id}"
            )

            try:
                # Simple check if it looks like HTML
                is_html = (
                    content.strip().lower().startswith("<!doctype")
                    or "<html" in content.lower()
                )

                import html as html_module

                if is_html:
                    file_content = content
                else:
                    # Escape content to prevent XSS when wrapping as plain text
                    safe_content = html_module.escape(content)
                    # Wrap markdown/text in a basic styled container (using inline CSS to avoid external dependencies)
                    file_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Generated Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #e2e8f0; line-height: 1.6; margin: 0; padding: 20px; }}
        .container {{ max-width: 800px; margin: 0 auto; background-color: #1e293b; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); border: 1px solid #334155; overflow: hidden; }}
        .header {{ background-color: #334155; padding: 10px 20px; border-bottom: 1px solid #475569; display: flex; align-items: center; gap: 8px; }}
        .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
        .red {{ background-color: #f87171; }} .amber {{ background-color: #fbbf24; }} .emerald {{ background-color: #34d399; }}
        .title {{ font-family: monospace; font-size: 12px; color: #94a3b8; margin-left: 8px; }}
        .content {{ padding: 30px; white-space: pre-wrap; word-wrap: break-word; font-size: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="dot red"></div><div class="dot amber"></div><div class="dot emerald"></div>
            <span class="title">generated_report.html</span>
        </div>
        <div class="content">{safe_content}</div>
    </div>
</body>
</html>"""

                filename = "generated_report.html"
                file_manager = get_file_manager()
                storage = get_storage_manager()
                context_manager = get_context_manager()

                # PRE-INJECTION: Append raw_context BEFORE any saving (Fix Storage Inconsistency)
                final_content = file_content
                if raw_context:
                    from src.crewai_enterprise.utils.html_context import (
                        append_context_section,
                    )

                    final_content = append_context_section(
                        final_content, raw_context, max_len=100_000
                    )

                # 1. Save locally (now contains context)
                file_info = file_manager.save_file_from_bytes(
                    chat_id=chat_id,
                    content=final_content.encode("utf-8"),
                    filename=filename,
                )

                # 2. Upload to Qiniu (now contains context)
                upload_res = storage.upload_file(
                    data=final_content.encode("utf-8"),
                    filename=filename,
                    content_type="text/html",
                )

                # 3. Save Context
                context_manager.save_file(
                    chat_id=chat_id,
                    sender_id=f"bot_{bot_type}",
                    sender_name=bot_type,
                    file_uri=upload_res.url,
                    filename=filename,
                    mime_type="text/html",
                    bot_type=bot_type,
                    storage_key=upload_res.key,
                )

                # Return summary + link
                summary = content.strip().split("\n")[0]
                if len(summary) > 60:
                    summary = summary[:57] + "..."

                return f"{summary}\n📄 云端链接: {upload_res.url}"
            except Exception as fallback_err:
                logger.error(
                    f"[AIBOT_FILE] Fallback file processing failed: {fallback_err}"
                )
                return content  # Graceful return of text if file logic fails
        else:
            return content

    cleaned_content = content
    file_manager = get_file_manager()
    storage = get_storage_manager()
    context_manager = get_context_manager()

    # Process tags from last to first to maintain correct string indices after replacement
    for i in range(len(open_tags) - 1, -1, -1):
        match = open_tags[i]
        original_filename = match.group(1)
        start_pos = match.end()

        # Determine end of file content (either next opening tag or end of string)
        # But we also search for a closing tag within this range
        next_tag_start = (
            open_tags[i + 1].start() if i + 1 < len(open_tags) else len(content)
        )
        segment = content[start_pos:next_tag_start]

        closing_match = re.search(r"</FILE>", segment, re.IGNORECASE)
        if closing_match:
            file_content = segment[: closing_match.start()]
            full_tag_end_pos = start_pos + closing_match.end()
        else:
            # Fallback for truncated/unclosed tags: take until next tag or end
            file_content = segment
            full_tag_end_pos = next_tag_start
            logger.warning(
                f"[AIBOT_FILE] Tag for {original_filename} was not closed, taking content until end/next tag"
            )

        try:
            filename = _sanitize_filename(original_filename)
            logger.info(
                f"[AIBOT_FILE] Processing generated file: {filename} (original: {original_filename}, {len(file_content)} chars)"
            )

            # 1. Pre-process and Append raw_context (ensure both local and cloud copies match)
            mime_type = (
                "text/html"
                if filename.endswith(".html") or filename.endswith(".htm")
                else "text/plain"
            )
            final_content = file_content

            if raw_context and mime_type == "text/html":
                from src.crewai_enterprise.utils.html_context import (
                    append_context_section,
                )

                final_content = append_context_section(
                    final_content, raw_context, max_len=100_000
                )
                logger.info(f"[AIBOT_FILE] Appended raw_context to {filename}")

            # 2. Save to local storage (consistent with fallback logic)
            file_info = file_manager.save_file_from_bytes(
                chat_id=chat_id,
                content=final_content.encode("utf-8"),
                filename=filename,
            )

            # 3. Upload to Qiniu (consistent with local content)
            cloud_url = None
            cloud_key = None
            try:
                upload_res = storage.upload_file(
                    data=final_content.encode("utf-8"),
                    filename=filename,
                    content_type=mime_type,
                )
                cloud_url = upload_res.url
                cloud_key = upload_res.key
                logger.info(f"[AIBOT_FILE] Uploaded to Qiniu: {cloud_url}")
            except Exception as qiniu_err:
                logger.error(f"[AIBOT_FILE] Qiniu upload failed: {qiniu_err}")
                cloud_url = None  # ensure fallback to local is clear

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
                    mime_type="text/html"
                    if filename.endswith(".html")
                    else "text/plain",
                    bot_type=bot_type,
                    storage_key=cloud_key,
                )
                logger.info(f"[AIBOT_FILE] Saved generated file to context: {filename}")
            except Exception as ctx_err:
                logger.error(f"[AIBOT_FILE] Failed to save to context: {ctx_err}")

            # Note: WeCom intelligent robot response_url does NOT support file message type
            # Only text/markdown messages are supported, so we skip file attachment sending
            # The cloud link in the text response is sufficient
            logger.info(
                f"[AIBOT_FILE] File available at cloud link (robot response_url does not support file attachments)"
            )

            # 5. Final text cleanup (replace the entire tag with info)
            display_url = cloud_url if cloud_url else "(上传去云端失败，仅保存本地)"

            # Extract summary: first line of text before the first <FILE> tag
            summary_text = ""
            if i == 0:  # Only extract summary for the first file
                pre_tag_content = content[: match.start()].strip()
                if pre_tag_content:
                    # Take only the first line, truncate to 100 chars
                    first_line = pre_tag_content.split("\n")[0].strip()
                    if len(first_line) > 100:
                        summary_text = first_line[:97] + "..."
                    else:
                        summary_text = first_line
                    logger.info(f"[AIBOT_FILE] Extracted summary: {summary_text}")

            if file_only_mode:
                # In file_only_mode, return link + summary (with fallback)
                if summary_text:
                    return f"📄 云端链接: {display_url}\n✨ {summary_text}"
                else:
                    # Fallback description when LLM omits summary
                    return f"📄 云端链接: {display_url}\n✨ 已生成HTML文件"
            else:
                if summary_text:
                    link_display = f"\n\n✨ {summary_text}\n📄 云端链接: {display_url}"
                else:
                    # Fallback description when LLM omits summary
                    link_display = f"\n\n✨ 已生成HTML文件\n📄 云端链接: {display_url}"
                cleaned_content = (
                    cleaned_content[: match.start()]
                    + link_display
                    + cleaned_content[full_tag_end_pos:]
                )

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
    quoted_content: str | None = None,
    quoted_msg_id: str | None = None,
    quoted_filename: str | None = None,
    response_url: str | None = None,
    file_output_mode: bool = False,
) -> None:
    """Call the appropriate LLM asynchronously and update task result."""
    print(
        f"[LLM_ASYNC_START] stream_id={stream_id} content={content[:50]!r}", flush=True
    )

    cleaned_content, context_window = extract_context_prefix(content)
    if cleaned_content != content:
        content = cleaned_content
    context_block = None
    if context_window is not None:
        context_block = _build_wecom_context_block(chat_id, context_window)

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

            cmd_result = _handle_prompt_command(
                command, args, bot_type, chat_id, user_id
            )
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
                    gitlab_base_url = (
                        cached_context["gitlab_url"]
                        if cached_context
                        else os.getenv("GITLAB_URL", "https://gitlab.goldenstand.com")
                    )
                    gitlab_token = os.getenv("GITLAB_TOKEN")

                    if gitlab_token:
                        try:
                            flow = CodebaseQAFlow(
                                gitlab_url=gitlab_base_url,
                                private_token=gitlab_token,
                                project_id=project_path,
                                query=inline_question,
                                branch=cmd_result.get("branch", "main"),
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

                            logger.info(
                                f"[CODEBASE_CMD] Completed inline QA for {chat_id}"
                            )
                            return

                        except Exception as e:
                            logger.error(f"[CODEBASE_CMD] Inline QA failed: {e}")
                            if stream_id in _stream_tasks:
                                _stream_tasks[stream_id]["content"] = (
                                    f"❌ 代码分析失败: {e}"
                                )
                                _stream_tasks[stream_id]["finished"] = True
                                _stream_tasks[stream_id]["completed_at"] = time.time()
                            return
                    else:
                        if stream_id in _stream_tasks:
                            _stream_tasks[stream_id]["content"] = (
                                "❌ GITLAB_TOKEN 未配置"
                            )
                            _stream_tasks[stream_id]["finished"] = True
                            _stream_tasks[stream_id]["completed_at"] = time.time()
                        return

                # Check if command wants to continue with LLM (e.g., /file-html, /file-html-daily)
                if cmd_result.get("continue_with_llm"):
                    # File output mode - continue to normal LLM flow
                    file_output_mode = cmd_result.get("file_output_mode", False)
                    template_name = cmd_result.get(
                        "template_name"
                    )  # None for free-form, "daily" or "meeting" for templates
                    date_range = cmd_result.get(
                        "date_range", "last_24h"
                    )  # Time range for archive query

                    # Archive context range from /Nd commands (e.g., /1d, /1w)
                    archive_context_range = cmd_result.get("archive_context_range")
                    if archive_context_range:
                        logger.info(
                            f"[ARCHIVE_CTX] Explicit archive range: {archive_context_range}"
                        )
                    # Replace content with user's actual request (remove /file-html prefix)
                    content = cmd_result.get("user_request", content)
                    logger.info(
                        f"[FILE_OUTPUT] Continuing to LLM with file_output_mode={file_output_mode}, template={template_name}, date_range={date_range}"
                    )
                    # Fall through to normal LLM processing below
                elif cmd_result.get("continue_with_question"):
                    # [FIX] Combined command (e.g., /reset question)
                    logger.info(
                        f"[CMD_FLOW] Command /{command} continuing with question: {cmd_result['continue_with_question'][:50]}..."
                    )
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
                        _stream_tasks[stream_id]["content"] = cmd_result.get(
                            "content", "命令已执行"
                        )
                        _stream_tasks[stream_id]["finished"] = True
                        _stream_tasks[stream_id]["completed_at"] = time.time()

                    logger.info(
                        f"[PROMPT_CMD] Handled command /{command} for {bot_type} in {chat_id}"
                    )
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

    try:
        archive_context_range
    except NameError:
        archive_context_range = None

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
    is_url_only = (
        len(content_stripped) == len(gitlab_match.group(0)) if gitlab_match else False
    )

    is_review_request = gitlab_match and (
        (has_positive_keyword and not has_negative_keyword) or is_url_only
    )

    if is_review_request:
        try:
            protocol = gitlab_match.group(1)
            domain = gitlab_match.group(2)
            project_path = gitlab_match.group(3)
            commit_sha = gitlab_match.group(4)
            gitlab_base_url = f"{protocol}{domain}"

            logger.info(
                f"[GITLAB_REVIEW] Detected review request: {gitlab_base_url} {project_path} {commit_sha}"
            )

            # Save project context for future QA (including the GitLab host)
            _user_project_context[chat_id] = {
                "project_path": project_path,
                "gitlab_url": gitlab_base_url,
            }

            # Update status to "Reviewing"
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = (
                    "🔄 正在运行中：Agent代码审查，请稍候...\n(架构/总能力/测试专家正在分析)"
                )

            # Get token from env
            gitlab_token = os.getenv("GITLAB_TOKEN")
            if not gitlab_token:
                raise ValueError("GITLAB_TOKEN environment variable not set")

            # Run Flow
            flow = CodeReviewFlow(
                gitlab_url=gitlab_base_url,
                private_token=gitlab_token,
                project_id=project_path,
                commit_sha=commit_sha,
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
                logger.info(
                    f"[FILE_OUTPUT] Added daily template JSON schema to system prompt"
                )
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
                logger.info(
                    f"[FILE_OUTPUT] Added meeting template JSON schema to system prompt"
                )
            else:
                # Free-form HTML mode (template_name is None)
                file_instruction = (
                    "\n\n[CRITICAL SYSTEM REQUIREMENT: FILE OUTPUT MODE]\n"
                    "The user explicitly requested an HTML file. You MUST follow this structure REGARDLESS of your adopted persona or style:\n"
                    "1. SUMMARY: A single sentence (max 50 chars) describing your generation.\n"
                    '2. CONTENT: The complete HTML content wrapped inside <FILE name="output.html">...</FILE> tags.\n'
                    "3. STYLING: Use Tailwind CSS CDN for all styling.\n"
                    "Do NOT include raw conversation logs or context in your HTML. The system will append it.\n"
                    "Failure to use the <FILE> tags will break the system integration. This is a mandatory technical requirement.\n\n"
                    "Example Output:\n"
                    "生成了一份风格简洁的分析报告。\n"
                    '<FILE name="report.html"><html>...</html></FILE>'
                )
                logger.info(
                    f"[FILE_OUTPUT] Added highly authoritative free-form HTML instruction to system prompt"
                )
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

        # Phase 2: Archive Context Injection - ALWAYS ON (default 3h)
        # Priority: explicit /Nd command > file_output_mode date_range > default 3h
        archive_context = ""
        is_report_request = file_output_mode  # Only mark as report for file output

        # Determine effective archive range
        ctx_start = None
        if archive_context_range:
            effective_range = archive_context_range
            # Explicit /Nd commands bypass /reset
            ctx_start = None
        elif file_output_mode:
            effective_range = date_range
            # File generation commands also usually want the full range
            ctx_start = None
        else:
            effective_range = "3h"  # Default for all normal conversations
            # Default 3h injection respects /reset
            ctx_start = context_manager.storage._run(
                action="get_context_start", chat_id=chat_id, bot_type=bot_type
            )
            if ctx_start == "None":
                ctx_start = None

        logger.info(
            f"[ARCHIVE_CTX] Injecting archive context, chat={chat_id}, range={effective_range}, respect_reset={ctx_start is not None}"
        )
        history = get_merged_chat_history(
            chat_id, date=effective_range, limit=500, context_start_ts=ctx_start
        )
        if history:
            archive_context = _format_chat_history(history)
            logger.info(
                f"[ARCHIVE_CTX] Injected {len(history)} messages from archive ({effective_range})"
            )
        else:
            logger.info(
                f"[ARCHIVE_CTX] No history found for {effective_range} in chat={chat_id}"
            )

        if file_output_mode and archive_context:
            system_prompt = (
                system_prompt
                + "\n\n[ARCHIVE_CONTEXT]\n"
                + archive_context
                + "\n[END_ARCHIVE_CONTEXT]\n"
                + "Do NOT include raw context in your output. The system will append it."
            )

        url_contents = []
        if urls:
            logger.info(f"[URL_DETECT] Found {len(urls)} URL(s) in message")
            for url in urls[:3]:  # Limit to first 3 URLs to avoid overload
                url_content = await _fetch_url_content(url)
                if url_content:
                    url_contents.append(
                        {
                            "url": url,
                            "content": url_content[
                                :8000
                            ],  # Limit to 8000 chars per URL
                        }
                    )

        # Get conversation history
        messages = context_manager.get_messages_for_llm(
            chat_id,
            system_prompt=system_prompt,
            bot_type=bot_type,
        )
        if context_block and messages and messages[-1]["role"] == "user":
            messages[-1]["content"] = (
                f"{context_block}\n\n---\n\n{messages[-1]['content']}"
            )
        # If URLs were fetched, prepend their content to the user's message context
        if url_contents:
            url_context = "\n\n---\n\n".join(
                [
                    f"**网页内容摘要自 {uc['url']}:**\n\n{uc['content']}"
                    for uc in url_contents
                ]
            )
            # Prepend URL content to the latest user message
            if messages and messages[-1]["role"] == "user":
                messages[-1]["content"] = (
                    f"{url_context}\n\n---\n\n用户问题：{messages[-1]['content']}"
                )
                logger.info(
                    f"[URL_CTX] Added {len(url_contents)} URL(s) content to context"
                )

        # Inject Archive Context if available
        if (
            archive_context
            and messages
            and messages[-1]["role"] == "user"
            and not file_output_mode
        ):
            messages[-1]["content"] = (
                f"### 今日群聊记录摘要 (仅供参考):\n\n{archive_context}\n\n"
                f"---\n\n基于以上对话内容，请根据要求执行：{messages[-1]['content']}"
            )

        def _finish_early(message: str, *, is_error: bool = False) -> None:
            if stream_id in _stream_tasks:
                _stream_tasks[stream_id]["content"] = message
                _stream_tasks[stream_id]["finished"] = True
                _stream_tasks[stream_id]["completed_at"] = time.time()
                if is_error:
                    _stream_tasks[stream_id]["error"] = True
            context_manager.add_message(
                chat_id=chat_id,
                sender_id=f"bot_{bot_type}",
                sender_name=f"{bot_type}",
                content=message,
                role="assistant",
                bot_type=bot_type,
            )

        file_ctx = None
        skip_sticky_file = False
        skip_extracted_injection = False
        strict_media_quote = False
        ocr_notice_prefix = ""

        # Quoted media resolution (fail fast, explicit)
        if quoted_msg_id or quoted_filename:
            if is_media_quote(quoted_content, quoted_filename):
                strict_media_quote = True
                skip_sticky_file = True
                try:
                    media_result = resolve_quoted_media(
                        chat_id=chat_id,
                        quoted_msg_id=quoted_msg_id,
                        quoted_filename=quoted_filename,
                        bot_type=bot_type,
                    )
                except QuotedMediaError as e:
                    msg = f"❗引用文件解析失败: {e}"
                    logger.error(f"[AIBOT_QUOTE] {msg}")
                    _finish_early(msg, is_error=True)
                    return

                if media_result.status == "file_ctx" and media_result.file_ctx:
                    file_ctx = media_result.file_ctx
                    skip_extracted_injection = True
                    logger.info(
                        f"[AIBOT_QUOTE] Using quoted file context: {media_result.reason}"
                    )
                elif media_result.status == "ocr_only" and media_result.ocr_text:
                    skip_extracted_injection = True
                    ocr_notice_prefix = "⚠️ 未获取到原图/原文件，仅基于OCR文本回答。\n\n"
                    ocr_snippet = media_result.ocr_text[:5000]
                    if messages and messages[-1]["role"] == "user":
                        messages[-1]["content"] = (
                            f"[Quoted OCR Content]\n{ocr_snippet}\n\n{messages[-1]['content']}"
                        )
                    logger.info(
                        f"[AIBOT_QUOTE] Using OCR-only fallback ({len(ocr_snippet)} chars)"
                    )
                elif media_result.status in ("pending", "not_found"):
                    try:
                        sync_status = trigger_archive_sync(
                            reason=f"quoted_media:{quoted_msg_id or quoted_filename}"
                        )
                        msg = "引用的图片/文件尚未同步完成，已触发同步，请稍后重试。"
                        logger.warning(f"[AIBOT_QUOTE] {msg} ({sync_status})")
                    except ArchiveSyncError as e:
                        msg = f"❗引用文件未就绪，且触发同步失败: {e}"
                        logger.error(f"[AIBOT_QUOTE] {msg}")
                    _finish_early(msg, is_error=True)
                    return
                else:
                    msg = f"❗引用文件解析失败: {media_result.reason}"
                    logger.error(f"[AIBOT_QUOTE] {msg}")
                    _finish_early(msg, is_error=True)
                    return

        # 1. Quoted File (Specific)
        if not file_ctx and not strict_media_quote and quoted_msg_id:
            # Try original ID first
            file_ctx = context_manager.get_active_file(
                chat_id, wecom_msg_id=quoted_msg_id, bot_type=bot_type
            )
            if not file_ctx:
                # Fallback: try derived image ID (file_{id}) to maintain vision quote matching
                file_ctx = context_manager.get_active_file(
                    chat_id, wecom_msg_id=f"file_{quoted_msg_id}", bot_type=bot_type
                )

            if file_ctx:
                logger.info(
                    f"[AIBOT_CTX] Found quoted file by MsgId: {file_ctx['filename']}"
                )

        if not file_ctx and not strict_media_quote and quoted_filename:
            file_ctx = context_manager.get_active_file(
                chat_id, filename=quoted_filename, bot_type=bot_type
            )
            if file_ctx:
                logger.info(
                    f"[AIBOT_CTX] Found quoted file by Filename: {file_ctx['filename']}"
                )

        # 2. Latest File (Sticky/Global) - with 10-minute time window
        if not file_ctx and not skip_sticky_file:
            file_ctx = context_manager.get_active_file(
                chat_id, limit=50, bot_type=bot_type
            )

            # Check if file is within 10-minute window
            if file_ctx:
                file_timestamp = file_ctx.get("timestamp", 0)
                elapsed_minutes = (time.time() - file_timestamp) / 60

                if elapsed_minutes > 10:
                    logger.info(
                        f"[AIBOT_CTX] File expired (age: {elapsed_minutes:.1f}min > 10min), ignoring sticky context"
                    )
                    file_ctx = None  # Expired, don't use

        extracted_record = None
        if (file_ctx or quoted_msg_id) and not skip_extracted_injection:
            store = FileContentStore()
            if file_ctx:
                file_hash = file_ctx.get("hash")
                if file_hash:
                    extracted_record = store.get_by_hash(file_hash)
                if not extracted_record:
                    storage_key = file_ctx.get("storage_key")
                    if storage_key:
                        extracted_record = store.get_by_storage_key(storage_key)
                if not extracted_record:
                    uri = file_ctx.get("uri")
                    if uri and uri.startswith("http"):
                        extracted_record = store.get_by_storage_key(uri)

            if not extracted_record and quoted_msg_id:
                extracted_record = store.get_by_msg_id(quoted_msg_id)
                if not extracted_record and quoted_msg_id.startswith("file_"):
                    extracted_record = store.get_by_msg_id(quoted_msg_id[5:])

            if extracted_record and extracted_record.extracted_text:
                label = extracted_record.filename or (
                    file_ctx.get("filename") if file_ctx else "file"
                )
                snippet = extracted_record.extracted_text[:5000]
                extracted_block = f"[Extracted Content: {label}]\n{snippet}"
                if messages and messages[-1]["role"] == "user":
                    messages[-1]["content"] = (
                        f"{extracted_block}\n\n{messages[-1]['content']}"
                    )
                logger.info(
                    f"[AIBOT_CTX] Injected extracted text for {label} ({len(snippet)} chars)"
                )

        use_file_context = False
        if file_ctx:
            # Check if provider supports file analysis
            supports_files = config.get("supports_file_analysis", False)

            if supports_files:
                use_file_context = True
                logger.info(
                    f"[AIBOT_CTX] Found file context for chat={chat_id}: {file_ctx['filename']} (UCS={not (file_ctx['uri'].startswith('content:') or file_ctx['uri'].startswith('base64:'))})"
                )
            else:
                logger.info(
                    f"[AIBOT_CTX] Skipping file context - {bot_type} does not support "
                    f"native file analysis (file: {file_ctx['filename']})"
                )
                if strict_media_quote:
                    msg = (
                        "❗当前机器人不支持文件/图片解析，请更换支持文件分析的机器人。"
                    )
                    logger.error(f"[AIBOT_QUOTE] {msg}")
                    _finish_early(msg, is_error=True)
                    return
                file_ctx = None  # Clear it, don't use

        logger.info(
            f"[AIBOT_LLM_REQ] bot={bot_type} provider={provider} chat={chat_id} "
            f"user={user_name} msg_count={len(messages)} file_ctx={use_file_context} content={content[:50]!r}..."
        )

        start_time = time.time()
        loop = asyncio.get_running_loop()
        current_user_content = messages[-1]["content"] if messages else content

        if use_file_context:
            try:
                # Format history for file chat (since chat_with_file takes text prompt)
                history_text = "\n\n".join(
                    [
                        f"{'用户' if m['role'] == 'user' else '模块'}: {m['content']}"
                        for m in messages
                    ]
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
                        f"```\n{raw_content}\n```\n\n用户新问题: {messages[-1]['content']}"  # Last msg is current query
                        # Note: messages[-1] is already in history_text, but emphasizing it here helps
                    )

                    response = await loop.run_in_executor(
                        None,
                        lambda: router.chat(
                            provider=provider,
                            messages=[{"role": "user", "content": full_prompt}],
                        ),
                    )
                elif file_uri and file_uri.startswith("base64:"):
                    # Inline Base64 Context (PDF/Images)
                    raw_b64 = file_uri[7:]
                    file_bytes = base64.b64decode(raw_b64)
                    full_prompt = f"对话历史:\n{history_text}\n\n（提示：用户之前上传了文件 {filename}，请基于文件内容回答）"

                    # Fetch limited history for file analysis to avoid hallucinating old results
                    context = context_manager.get_context(chat_id, bot_type=bot_type)
                    limited_messages = (
                        context.messages[-5:]
                        if len(context.messages) > 5
                        else context.messages
                    )

                    file_messages = []
                    if system_prompt:
                        file_messages.append(
                            {"role": "system", "content": system_prompt}
                        )
                    for msg in limited_messages:
                        file_messages.append(
                            {
                                "role": msg.get("role", "user"),
                                "content": msg.get("content", ""),
                            }
                        )
                    # Use the latest message content to preserve any injected context
                    file_messages.append(
                        {"role": "user", "content": current_user_content}
                    )

                    response = await loop.run_in_executor(
                        None,
                        lambda: router.chat_with_file(
                            provider=provider,
                            text=file_messages[-1]["content"],
                            file_data=file_bytes,
                            file_mime_type=file_ctx["mime"],
                            filename=filename,
                            history=file_messages[:-1],
                            system_prompt=system_prompt,
                            max_tokens=4096,
                        ),
                    )
                else:
                    # Cloud URI Context (UCS Phase 1)
                    # For Qiniu/S3, we might need to download it first if the LLM doesn't support direct URLs
                    # Or for Gemini, if it's already a Gemini File API URI, use it directly.

                    full_prompt = f"对话历史:\n{history_text}\n\n（提示：用户之前上传了文件 {filename}，请基于文件内容回答）"

                    is_gemini_uri = file_uri.startswith(
                        "https://generativelanguage.googleapis.com"
                    )

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
                            ),
                        )
                    else:
                        try:
                            # Fix: Use signed URL for private buckets (Auditor Refinement)
                            storage = get_storage_manager()
                            storage_key = file_ctx.get("storage_key")

                            if storage_key:
                                if storage_key.startswith("http"):
                                    signed_url = storage_key
                                    logger.info(
                                        f"[AIBOT_CTX] Using direct URL (storage_key is full URL): {signed_url[:100]}..."
                                    )
                                else:
                                    # Genuine cloud file with key -> Generate signed URL (1 hour)
                                    signed_url = storage.get_url(
                                        storage_key, expires_in_seconds=3600
                                    )
                                    logger.info(
                                        f"[AIBOT_CTX] Using signed URL for cloud access: {signed_url[:100]}..."
                                    )
                            else:
                                # Legacy message (no key) -> Fallback to using URI directly
                                signed_url = file_uri
                                logger.info(
                                    f"[AIBOT_CTX] Fallback: using direct file URI (legacy context): {signed_url[:100]}..."
                                )

                            # Use requests to download
                            # For local file://, use open()
                            if signed_url.startswith("file://"):
                                with open(signed_url[7:], "rb") as f:
                                    file_bytes = f.read()
                            else:
                                # Auditor Refinement: Security-first approach for cloud downloads
                                verify_ssl = (
                                    os.getenv("STORAGE_VERIFY_SSL", "true").lower()
                                    == "true"
                                )
                                allow_fallback = (
                                    os.getenv(
                                        "STORAGE_ALLOW_HTTP_FALLBACK", "false"
                                    ).lower()
                                    == "true"
                                )

                                if not verify_ssl:
                                    urllib3.disable_warnings(
                                        urllib3.exceptions.InsecureRequestWarning
                                    )

                                try:
                                    download_res = requests.get(
                                        signed_url, timeout=30, verify=verify_ssl
                                    )
                                    download_res.raise_for_status()
                                except (
                                    requests.exceptions.SSLError,
                                    requests.exceptions.ConnectionError,
                                ) as ssl_err:
                                    # Only fallback to HTTP if explicitly allowed (e.g. for test/internal environments)
                                    if (
                                        allow_fallback
                                        and "handshake failure" in str(ssl_err).lower()
                                        and signed_url.startswith("https://")
                                    ):
                                        http_url = signed_url.replace(
                                            "https://", "http://", 1
                                        )
                                        logger.warning(
                                            f"[AIBOT_CTX] SSL handshake failure, retrying with HTTP (opt-in fallback): {http_url[:100]}..."
                                        )
                                        download_res = requests.get(
                                            http_url, timeout=30
                                        )
                                        download_res.raise_for_status()
                                    else:
                                        logger.error(
                                            f"[AIBOT_CTX] Download failed (SSL verify={verify_ssl}, fallback={allow_fallback}): {ssl_err}"
                                        )
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
                                ),
                            )
                        except Exception as download_err:
                            logger.error(
                                f"[AIBOT_CTX] Failed to download cloud file: {download_err}"
                            )
                            raise download_err
            except Exception as e:
                if strict_media_quote:
                    msg = f"❗引用文件解析失败（无法读取文件内容）: {str(e)[:100]}"
                    logger.error(f"[AIBOT_QUOTE] {msg}")
                    _finish_early(msg, is_error=True)
                    return
                logger.warning(
                    f"[AIBOT_CTX] Failed to use file context (fallback to text): {e}"
                )
                use_file_context = False
                # Auditor Suggestion: If file context was expected but failed, notify the user.
                context_error_hint = f"\n\n（提示：需补充历史图片/文件，本次回答仅基于纯文本记录。错误：{str(e)[:50]}...）"

        if not use_file_context:
            # Run standard LLM call
            response = await loop.run_in_executor(
                None, lambda: router.chat(provider=provider, messages=messages)
            )
            # Apply error hint if context failed
            if "context_error_hint" in locals() and context_error_hint:
                response.content += context_error_hint

        elapsed_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"[AIBOT_LLM_RES] bot={bot_type} elapsed={elapsed_ms}ms "
            f"response_len={len(response.content)} content={response.content[:50]!r}..."
        )

        if ocr_notice_prefix:
            response.content = f"{ocr_notice_prefix}{response.content}"

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
            f"prompt={prompt[:50]!r}... image_size={len(image_base64) // 1024}KB"
        )

        start_time = time.time()

        # Fetch limited history (last 5 messages) for vision LLM call to prevent history-based hallucinations
        context = context_manager.get_context(chat_id, bot_type=bot_type)
        limited_messages = (
            context.messages[-5:] if len(context.messages) > 5 else context.messages
        )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for msg in limited_messages:
            messages.append(
                {"role": msg.get("role", "user"), "content": msg.get("content", "")}
            )
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
            ),
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
