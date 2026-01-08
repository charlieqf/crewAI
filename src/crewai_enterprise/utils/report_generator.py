"""
Report Generator - Converts structured LLM JSON into a visual HTML report.
"""

import json
import logging
import os # Added import for os module
from datetime import datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# UTC+8 Timezone for Beijing
BEIJING_TZ = timezone(timedelta(hours=8))

# Template directory configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DEFAULT_TEMPLATE = "daily_report.html"

def generate_html_report(json_data: str, room_id: str, room_name: str = None) -> tuple[str, bool]:
    """
    Parses LLM JSON output and renders the daily report HTML.
    Returns (html_content, is_success).
    """
    try:
        # 1. Clean and parse JSON (strip markdown blocks if present)
        clean_json = json_data.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[-1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[-1].split("```")[0].strip()
            
        data = json.loads(clean_json)
        
        # Mandatory field check for success
        if "topics" not in data and "todos" not in data:
            raise ValueError("Missing critical fields: topics or todos")
            
    except Exception as e:
        logger.error(f"Failed to parse report JSON: {e}")
        # Fallback for broken JSON: wrap raw text in a basic message
        fail_html = f"<html><body><h2>生成报告失败</h2><p>解析 LLM 输出时出错: {e}</p><pre>{json_data}</pre></body></html>"
        return fail_html, False

    # 2. Add metadata (Beijing Time)
    now_bj = datetime.now(BEIJING_TZ)
    render_data = {
        "room_id": room_id,
        "room_name": room_name or room_id,
        "date": now_bj.strftime("%Y年%m月%d日"),
        "timestamp": now_bj.strftime("%Y-%m-%d %H:%M:%S"),
        "topics": data.get("topics", []),
        "todos": data.get("todos", []),
        "insights": data.get("insights", []),
        "participant_count": data.get("participant_count", 0)
    }

    # 3. Render Template
    try:
        env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
        template = env.get_template(DEFAULT_TEMPLATE)
        html = template.render(**render_data)
        return html, True
    except Exception as e:
        logger.error(f"Template rendering failed: {e}")
        fail_html = f"<html><body><h2>模板渲染失败</h2><p>{e}</p></body></html>"
        return fail_html, False

if __name__ == "__main__":
    # Test
    test_json = """
    {
      "topics": [
        {"title": "数据库隔离讨论", "summary": "团队讨论了将 Archive 和 Bot 的数据库隔离，以避免 SQLite 锁竞争。", "msgids": ["1", "2"], "sentiment": "positive"},
        {"title": "VPN 修复进展", "status": "VPN 已恢复连接，使用了正确的 strongswan 服务名。", "msgids": ["3"]}
      ],
      "todos": [
        {"task": "部署新版 aibot_callback.py", "assignee": "@rdpuser"},
        {"task": "验证每日报告功能", "assignee": "@gemini"}
      ],
      "insights": ["数据库锁是主要的性能瓶颈", "VPN 配置对 Ubuntu 22.04 有特定要求"],
      "participant_count": 3
    }
    """
    print(generate_html_report(test_json, "test_room", "测试群聊"))
