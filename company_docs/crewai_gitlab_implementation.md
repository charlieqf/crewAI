# CrewAI + GitLab 软件开发自动化方案

本计划旨在解决小型软件公司在 GitLab 上的自动化 Code Review 以及跨团队 AI 协同讨论室的需求。

---

## 需求 1: 基于 GitLab 提交的自动化 Code Review

### 实现原理与工作机制
这个需求本质上是一个**事件驱动的自动化流**。

1.  **事件外传 (webhook)**：当工程师执行 `git push` 时，GitLab 会向您预设的服务器发送一个 JSON 数据包。
2.  **流式处理 (Flows)**：利用 CrewAI 的 **Flows** 处理异步事件流，结合 **Custom Tools** 与 GitLab API 和通知系统对接。
    -   **状态保持**：Flow 会记录当前处理的是哪个 Commit，评审是否成功，避免重复评审。
    -   **并行审计**：它可以同时启动“代码安全”和“业务逻辑”两个 Agent，互不干扰，提高速度。
3.  **专家审计 (The Crew)**：启动一个包含两个角色的 Crew，AI 将评审意见汇总成 Markdown 文本。
    -   **Senior Code Reviewer**: 负责逻辑、架构和风格评审。根据您的“公司代码规范知识库”进行对比。
    -   **Security Auditor**: 负责查找代码中的安全漏洞（如硬编码密钥、注入口等）。
4.  **反馈闭环 (The Tool)**：由工具将结果推送到指定 Email、企业微信机器人，或在 GitLab MR 下发表评论。

### 框架现状（CrewAI 现在有什么？）
-   **成熟的编排能力**：完备的 Flow 异步任务框架和 Agent 协同逻辑。
-   **灵活的知识库**：内置多种 RAG 支持，可接入公司代码规范。
-   **工具模板**：提供了构建自定义工具（BaseTool）的标准模式。

### 定制开发（还需要您开发什么？）
-   **Webhook 接收器**：一个轻量级的接收服务（如 FastAPI），用于解析信号并触发 CrewAI。
-   **定制 `GitLabTool`**：针对私有环境开发 `get_diff()` 和 `post_comment()` 工具。
-   **评审标准 (Prompt)**：定义符合公司业务逻辑的评审规则。

---

## 需求 2: 协作式多 AI 聊天讨论室

### 实现原理与工作机制
这是一个**带长短期记忆的人机交互环境**，实现人机共创。

1.  **多模型并发 (Multi-LLM)**：讨论室后端连接多个 LLM 接口（GPT-4 用于设计，Gemini 用于实现）。
2.  **上下文接入 (RAG)**：将 GitLab 仓库文件转化为向量索引，让 AI 读取仓库内容。
3.  **交互协作 (Human-in-the-Loop)**：AI 在不确定时主动向群组成员发起询问。

### 框架现状（CrewAI 现在有什么？）
-   **Knowledge Base**：支持直接读取源代码文件夹建立临时知识库。
-   **Internal Memory**：内置 Short-term 和 Long-term 记忆机制。
-   **Manager Agent**：自动协调多个 AI 的发言和分工。

### 定制开发（还需要您开发什么？）
-   **讨论室 UI**：建议使用 Streamlit 快速搭建前端界面。
-   **仓库同步脚本**：定期或触发式更新代码索引。
-   **身份映射**：区分讨论中的人类角色。

---

## 验证与部署

### 自动化测试
-   **Tool Unit Tests**: 编写测试脚本验证 `GitLabTool` 能正确拉取 Diff 代码。
-   **Flow Integration Test**: 模拟 Webhook 数据包，验证端到端逻辑。

### 部署建议
-   **推荐平台**：CrewAI AOP (Enterprise 版) 提供了一键部署和实时可观测性。
-   **私有化**：亦可使用 Docker 容器化部署在您的本地服务器，配合本地 LLM (Ollama) 使用。

> [!IMPORTANT]
> 此方案需要您提供 GitLab 的 Access Token 以及企业微信机器人的 Webhook 地址。
