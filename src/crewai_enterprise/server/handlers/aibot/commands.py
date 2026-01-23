from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime

from src.crewai_enterprise.server.handlers.aibot.config import (
    BOT_CONFIGS,
    PROJECT_NICKNAMES,
    _user_project_context,
)
from src.crewai_enterprise.utils.chat_context import get_context_manager

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

**📄 文件生成命令（支持范围：1d/1w/3h等）：**
• `/file-html [时间] <描述>` - 自由生成HTML文件
• `/file-html-daily [时间]` - 生成群聊摘要报告
• `/file-html-meeting [时间]` - 生成会议纪要
  示例: `/file-html-daily 1w` (最近1周记录)
        `/file-html 3h 毒舌总结这三小时消息`
  💡 *生成的HTML底部包含：原始上下文（用于数据核对）*

**📁 上下文管理：**
• `/reset` - 彻底重置所有对话历史和上下文
• `/new` - 清除临时文件上下文，开始新话题
• Quote文件消息 - 明确引用特定文件

**📂 归档上下文（自动注入最近3小时群聊记录）：**
• `/1h`, `/3h`, `/1d`, `/1w` - 指定归档范围后提问
  示例: `/1d 昨天讨论了什么`
💡 *自动包含群聊消息和文件/图片提取的文字*

**💻 代码库分析：**
• `/codebase <gitlab_url>` - 设置代码库上下文
• 之后可直接提问代码相关问题，或发送截图分析

**📝 文件分析能力：**
• Gemini：✅ 支持大文件原生分析（PDF/DOC等）
• ChatGPT/Grok：❌ 仅支持图片和文本对话

**💡 使用技巧：**
1. 发送文件后10分钟内无需重复引用
2. 使用 /new 切换话题，避免旧文件干扰
3. 审查代码可以使用 /codebase 或发送 Commit URL
4. 自定义 Prompt 可让AI扮演特定角色（如毒舌、专家等）

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
            return {"content": "❌ 请提供有效的 prompt 内容\n\n用法：/set_prompt 你是一个中文的Python开发专家..."}
        
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
                response = "✅ 已清除文件上下文，开始新对话\n\n💡 之前的文件将不再自动使用，如无引用请重新发送或 Quote"
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
                    f"💡 历史记录已保存但不再被引用。\n"
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
                "- `/codebase https://gitlab.example.com/team/myproject 详细的务能力在哪里？`"
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
                "content": f"🔄 正在分析 `{project_path}` 代码库 (分支: `{branch}`)...",
                "continue_with_question": inline_question,
                "project_path": project_path,
                "branch": branch
            }
        
        # No question, just confirm context set
        response = (
            f"✅ 已设置代码库上下文: `{project_path}`\n"
            f"📌 当前分支: `{branch}`\n\n"
            f"现在你可以直接问，比如:\n"
            f"- \"这些被提在哪些文件中出现过？\"\n"
            f"- \"creditor_code 字段是在哪里处理的？\"\n"
            f"- \"项目的原始数据处理的逻辑链在哪里？\"\n\n"
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
            return {"content": "❌ 请提供生成描述\n\n用法：/file-html 做一个详细的项目跟踪\n      /file-html 1w 总结本周的对话"}
        
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
    
    # /1d, /1w, /3h etc. - Explicit archive time range for normal conversation
    elif re.match(r'^\d+[hdw]$', command):
        time_range = command.lower()
        user_request = args.strip() if args else ""
        
        # Require a question/topic when using time range commands
        if not user_request:
            return {"content": f"❌ 请在 /{time_range} 后输入问题\n\n示例: `/{time_range} 昨天讨论了什么`"}
        
        logger.info(f"[ARCHIVE_CMD] Explicit time range command: /{time_range}")
        return {
            "archive_context_range": time_range,
            "user_request": user_request,
            "continue_with_llm": True,
        }
    
    return None




