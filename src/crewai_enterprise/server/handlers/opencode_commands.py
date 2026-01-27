import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def handle_opencode_command(
    content: str,
    chat_id: str,
    user_id: str,
) -> Dict[str, Any] | None:
    """
    Parse and handle special OpenCode commands.
    
    Returns a dict with instruction if handled, else None.
    """
    text = content.strip()
    # Support both "/plan" and "@OpenCode /plan"
    # Match strings that start with "/" or have "/" after a mention/whitespace
    match = re.search(r'(?:^|\s)/([a-zA-Z0-9_-]+)(?:\s+(.*))?$', text)
    if not match:
        return None
        
    command = match.group(1).lower()
    args = match.group(2) if match.group(2) else ""
    
    if command == "help":
        return {
            "type": "response",
            "content": (
                "🛠️ **OpenCode 开发者指令**\n\n"
                "• `/plan <描述>` - 让 AI 生成或更新开发计划\n"
                "• `/status` - 查看当前 Task 进度和执行状态\n"
                "• `/config` - 查看当前项目配置（Repo, Branch 等）\n"
                "• `/reset` - 重置本轮对话上下文\n"
                "• `/help` - 打印此帮助屏幕\n\n"
                "💡 *可以直接输入指令开始工作，如：/plan 重构这部分代码*"
            )
        }
        
    if command == "plan":
        return {
            "type": "sdk_command",
            "command": "plan",
            "arguments": args
        }
        
    if command == "status":
        return {
            "type": "sdk_command",
            "command": "status",
            "arguments": args
        }

    if command == "config":
        return {
            "type": "bridge_action",
            "action": "show_config"
        }
        
    if command == "reset":
        return {
            "type": "bridge_action",
            "action": "reset_session"
        }
        
    return None
