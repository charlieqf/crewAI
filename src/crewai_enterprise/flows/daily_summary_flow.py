"""
Daily Summary Flow - CrewAI Flow for daily chat dialogue summary.

Orchestrates the Collector, Analyst, and Coordinator agents to:
1. Collect chat records from database
2. Analyze and categorize discussions
3. Generate and push summary report
"""

import os
from datetime import datetime
from typing import Optional

from crewai import Crew, Task
from crewai.flow.flow import Flow, listen, start

from ..agents.daily_summary_agents import (
    create_analyst_agent,
    create_collector_agent,
    create_coordinator_agent,
)
from ..tools.chat_storage.chat_storage_tool import ChatStorageTool

# Default DB path from environment or fallback - same as ChatContextManager
DEFAULT_CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "chat_storage.db")


class DailySummaryFlow(Flow):
    """Flow for generating daily dialogue summary reports."""

    def __init__(
        self,
        chat_id: str,
        db_path: str | None = None,
        date: Optional[str] = None,
        wecom_tool=None,
    ):
        super().__init__()
        self.chat_id = chat_id
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.db_path = db_path or DEFAULT_CHAT_DB_PATH
        self.wecom_tool = wecom_tool

        # Initialize tools
        self.chat_storage_tool = ChatStorageTool(db_path=self.db_path)

        # Initialize agents
        self.collector_agent = create_collector_agent(self.chat_storage_tool)
        self.analyst_agent = create_analyst_agent()
        self.coordinator_agent = create_coordinator_agent(wecom_tool)

    @start()
    def collect_messages(self):
        """Step 1: Collect all messages for the day."""
        collect_task = Task(
            description=f"""
            收集群组 {self.chat_id} 在 {self.date} 的所有对话记录。
            
            使用 Chat Storage Tool 的 get_by_date action:
            - action: get_by_date
            - chat_id: {self.chat_id}
            - date: {self.date}
            
            返回完整的对话记录，保持时间顺序。
            """,
            agent=self.collector_agent,
            expected_output="包含所有对话记录的 Markdown 格式文本",
        )

        crew = Crew(agents=[self.collector_agent], tasks=[collect_task], verbose=True)

        result = crew.kickoff()
        return str(result)

    @listen(collect_messages)
    def analyze_messages(self, messages: str):
        """Step 2: Analyze and categorize the collected messages."""
        if "没有找到" in messages or "No messages" in messages:
            return (
                f"## {self.date} 无对话记录\n\n今日群组 {self.chat_id} 暂无对话记录。"
            )

        analyze_task = Task(
            description=f"""
            分析以下对话记录，识别关键主题并分类：
            
            {messages}
            
            请将对话分为以下类别：
            1. 🔴 紧急问题 - Bug、故障、阻塞性问题
            2. 📋 技术决策 - 架构、技术选型、代码实现讨论
            3. 💼 商务机会 - 客户、销售、合作相关
            4. 📝 一般事务 - 日常沟通、会议安排
            
            为每个类别提供：
            - 主题摘要（一句话）
            - 涉及人员
            - 关键讨论点
            """,
            agent=self.analyst_agent,
            expected_output="结构化的分类分析报告",
        )

        crew = Crew(agents=[self.analyst_agent], tasks=[analyze_task], verbose=True)

        result = crew.kickoff()
        return str(result)

    @listen(analyze_messages)
    def generate_report(self, analysis: str):
        """Step 3: Generate the final summary report."""
        report_task = Task(
            description=f"""
            基于以下分析结果，生成《团队重点跟进事项列表》：
            
            {analysis}
            
            报告格式要求：
            
            # 📊 每日对话复盘报告
            **日期**: {self.date}
            **群组**: {self.chat_id}
            
            ## 🔴 紧急事项（需立即处理）
            - [ ] 事项描述 | 责任人 | 建议行动
            
            ## 📋 技术决策（需跟进）
            - [ ] 决策描述 | 涉及人员 | 下一步
            
            ## 💼 商务机会（需关注）
            - [ ] 机会描述 | 负责人 | 建议行动
            
            ## ✅ 今日总结
            一句话总结今日重点
            
            如果需要推送报告，使用 WeCom Tool 发送给管理员。
            """,
            agent=self.coordinator_agent,
            expected_output="Markdown 格式的每日复盘报告",
        )

        crew = Crew(agents=[self.coordinator_agent], tasks=[report_task], verbose=True)

        result = crew.kickoff()
        return str(result)


def run_daily_summary(
    chat_id: str,
    db_path: str | None = None,
    date: Optional[str] = None,
    wecom_tool=None,
) -> str:
    """
    Convenience function to run the daily summary flow.

    Args:
        chat_id: The chat/group ID to summarize
        db_path: Path to SQLite database (uses CHAT_DB_PATH env var if not specified)
        date: Date in YYYY-MM-DD format (defaults to today)
        wecom_tool: Optional WeComTool for pushing the report

    Returns:
        The generated summary report as a string
    """
    flow = DailySummaryFlow(
        chat_id=chat_id, db_path=db_path, date=date, wecom_tool=wecom_tool
    )

    return flow.kickoff()
