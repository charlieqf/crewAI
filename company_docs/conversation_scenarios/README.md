# 多轮对话场景文档概览

本目录包含企业微信 AI 机器人的所有多轮对话场景设计文档。

## 目的

- 穷尽所有对话场景
- 明确上下文管理策略
- 定义指令行为
- 理清 Agent 协作逻辑

## 架构视角

- [13_llm_vs_agent.md](13_llm_vs_agent.md) - **核心：LLM 对话 vs Agent 任务的区别**

## 场景分类

### 基础对话
- [01_basic_conversation.md](01_basic_conversation.md) - 基础多轮对话
- [02_context_management.md](02_context_management.md) - 上下文管理与限制

### 文件生成
- [03_file_html_generation.md](03_file_html_generation.md) - HTML 文件生成
- [04_file_iterative_refinement.md](04_file_iterative_refinement.md) - 文件迭代改进

### 代码分析
- [05_gitlab_code_review.md](05_gitlab_code_review.md) - GitLab 代码审查
- [06_codebase_qa.md](06_codebase_qa.md) - 代码库问答

### 文件处理
- [07_file_analysis.md](07_file_analysis.md) - 文件分析（PDF/图片）
- [08_file_quote_context.md](08_file_quote_context.md) - 文件引用与上下文

### Prompt 管理
- [09_custom_prompt.md](09_custom_prompt.md) - 自定义 Prompt
- [10_context_reset.md](10_context_reset.md) - 上下文重置

### 复杂场景
- [11_mixed_scenarios.md](11_mixed_scenarios.md) - 混合复杂场景 (Vision+Codebase, Multi-Bot)
- [12_archive_integration.md](12_archive_integration.md) - 对话存档集成与"深层记忆"

## 设计原则

1. **上下文隔离**：不同群聊的上下文完全隔离
2. **滑动窗口 + 深层检索**：短期记忆靠滑动窗口，长期记忆靠 Archive 检索
3. **指令优先级**：显式指令 > 隐式行为
4. **最小惊讶**：行为应符合用户预期
