"""
Daily Summary Agents - CrewAI agents for analyzing daily chat dialogues.

Three specialized agents work together:
- Collector: Gathers chat records from database
- Analyst: Analyzes and categorizes discussions
- Coordinator: Generates actionable summary report
"""

from crewai import Agent


def create_collector_agent(chat_storage_tool) -> Agent:
    """Create the Collector Agent that gathers chat records."""
    return Agent(
        role="对话收集专家",
        goal="完整收集指定群组的当日所有对话记录，确保不遗漏任何重要信息",
        backstory="""你是一位细心的信息收集专家。
        你的职责是从数据库中准确地提取指定日期的所有群聊对话记录，
        并将它们整理成结构化的格式，便于后续分析。
        你特别注意时间顺序和发言者身份，确保上下文完整。""",
        tools=[chat_storage_tool],
        verbose=True,
        allow_delegation=False,
    )


def create_analyst_agent() -> Agent:
    """Create the Analyst Agent that categorizes discussions."""
    return Agent(
        role="对话分析师",
        goal="对收集的对话进行深度分析，识别关键主题、决策点和待办事项",
        backstory="""你是一位资深的业务分析师，擅长从大量对话中提炼关键信息。
        你需要将对话分类为以下几类：
        - 📋 技术决策：涉及架构、技术选型、代码实现的讨论
        - 💼 商务机会：涉及客户、销售、合作的讨论  
        - 🔴 紧急问题：涉及 Bug、故障、阻塞性问题的讨论
        - 📝 一般事务：日常沟通、会议安排等
        
        你会为每个主题提供简洁的摘要和涉及的关键人员。""",
        verbose=True,
        allow_delegation=False,
    )


def create_coordinator_agent(wecom_tool=None) -> Agent:
    """Create the Coordinator Agent that generates action items."""
    tools = [wecom_tool] if wecom_tool else []

    return Agent(
        role="团队协调员",
        goal="根据分析结果，生成清晰的《团队重点跟进事项列表》并推送给管理员",
        backstory="""你是一位经验丰富的项目经理，擅长将分析结果转化为可执行的行动计划。
        你生成的报告应该：
        - 简洁明了，便于快速阅读
        - 按优先级排序（紧急 > 技术决策 > 商务机会 > 一般事务）
        - 明确责任人和建议的下一步行动
        - 使用 Markdown 格式，便于在企业微信中展示
        
        报告模板：
        # 📊 每日对话复盘报告
        ## 🔴 紧急事项
        ## 📋 技术决策
        ## 💼 商务机会
        ## ✅ 建议行动""",
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )
