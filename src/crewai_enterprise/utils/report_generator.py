"""
Report Generator - Converts structured LLM JSON into visual HTML reports.

Supports multiple templates:
- daily_report.html (default) - For daily chat summaries
- meeting_notes.html - For meeting minutes
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# UTC+8 Timezone for Beijing
BEIJING_TZ = timezone(timedelta(hours=8))

# Template directory configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

# Template configurations
TEMPLATES = {
    "daily": {
        "file": "daily_report.html",
        "required_fields": ["topics", "todos"],  # At least ONE of these is required
        "optional_fields": ["insights", "participant_count"]
    },
    "meeting": {
        "file": "meeting_notes.html", 
        "required_fields": ["agenda", "action_items"],  # At least ONE of these is required
        "optional_fields": ["title", "attendees", "next_meeting"]
    }
}


def _clean_json(raw_data: str) -> str:
    """Extract JSON from markdown code blocks if present."""
    clean = raw_data.strip()
    if "```json" in clean:
        clean = clean.split("```json")[-1].split("```")[0].strip()
    elif "```" in clean:
        # Try to find JSON block
        parts = clean.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("{") or part.startswith("["):
                clean = part
                break
    return clean


def render_template(
    json_data: str,
    template_name: str,
    room_id: str,
    room_name: str = None,
    raw_context: str = None
) -> tuple[str, bool]:
    """
    Generic template renderer.
    
    Args:
        json_data: JSON string from LLM
        template_name: One of 'daily', 'meeting'
        room_id: Chat room ID
        room_name: Optional display name
        raw_context: Optional raw chat context to append for debugging
        
    Returns:
        (html_content, is_success)
    """
    if template_name not in TEMPLATES:
        logger.error(f"Unknown template: {template_name}")
        return f"<html><body><h2>未知模板: {template_name}</h2></body></html>", False
    
    config = TEMPLATES[template_name]
    
    try:
        # 1. Clean and parse JSON
        clean_json = _clean_json(json_data)
        data = json.loads(clean_json)
        
        # 2. Validate required fields
        has_required = any(field in data for field in config["required_fields"])
        if not has_required:
            raise ValueError(f"Missing required fields. Need at least one of: {config['required_fields']}")
            
    except Exception as e:
        logger.error(f"Failed to parse template JSON: {e}")
        fail_html = f"<html><body><h2>生成报告失败</h2><p>解析 LLM 输出时出错: {e}</p><pre>{json_data[:500]}...</pre></body></html>"
        return fail_html, False

    # 3. Add metadata (Beijing Time)
    now_bj = datetime.now(BEIJING_TZ)
    render_data = {
        "room_id": room_id,
        "room_name": room_name or room_id,
        "date": now_bj.strftime("%Y年%m月%d日"),
        "timestamp": now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        **data  # Merge all JSON fields
    }

    # 4. Render Template
    try:
        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
        template = env.get_template(config["file"])
        html = template.render(**render_data)
        
        # Append raw context for transparency if provided
        if raw_context:
            import html as html_module
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
            # Insert before closing </body> tag
            if '</body>' in html:
                html = html.replace('</body>', f'{context_section}</body>')
            else:
                html += context_section
        
        logger.info(f"[TEMPLATE] Successfully rendered {template_name} template for {room_id}")
        return html, True
    except Exception as e:
        logger.error(f"Template rendering failed: {e}")
        fail_html = f"<html><body><h2>模板渲染失败</h2><p>{e}</p></body></html>"
        return fail_html, False


def generate_html_report(
    json_data: str,
    room_id: str,
    room_name: str = None,
    template_name: str = "daily",
    raw_context: str = None
) -> tuple[str, bool]:
    """
    Parses LLM JSON output and renders it using the specified template.
    
    Args:
        json_data: JSON string from LLM
        room_id: Chat room ID
        room_name: Optional display name
        template_name: Template to use ('daily' or 'meeting')
        raw_context: Optional raw chat context to append for debugging
        
    Returns:
        (html_content, is_success)
    """
    return render_template(json_data, template_name, room_id, room_name, raw_context)


def generate_meeting_notes_report(
    json_data: str,
    room_id: str,
    room_name: str = None
) -> tuple[str, bool]:
    """
    Convenience function for meeting notes template.
    """
    return render_template(json_data, "meeting", room_id, room_name)


if __name__ == "__main__":
    # Test daily report
    test_daily = """
    {
      "topics": [
        {"title": "数据库隔离讨论", "summary": "团队讨论了将 Archive 和 Bot 的数据库隔离。", "sentiment": "positive"},
        {"title": "VPN 修复进展", "summary": "VPN 已恢复连接。"}
      ],
      "todos": [
        {"task": "部署新版代码", "assignee": "@developer"}
      ],
      "participant_count": 3
    }
    """
    print("=== Daily Report ===")
    html, success = generate_html_report(test_daily, "test_room", "测试群聊", "daily")
    print(f"Success: {success}, Length: {len(html)}")
    
    # Test meeting notes
    test_meeting = """
    {
      "title": "产品评审会议",
      "attendees": ["张三", "李四", "王五"],
      "agenda": [
        {"item": "Q1 目标回顾", "discussion": "团队完成了 80% 的目标", "decisions": ["继续当前策略"]}
      ],
      "action_items": [
        {"task": "准备 Q2 计划", "owner": "张三", "due": "2026-01-15"}
      ],
      "next_meeting": "2026-01-15 14:00"
    }
    """
    print("\n=== Meeting Notes ===")
    html, success = generate_meeting_notes_report(test_meeting, "test_room", "测试群聊")
    print(f"Success: {success}, Length: {len(html)}")
