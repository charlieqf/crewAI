# 场景 05：GitLab 代码审查

## 场景描述

用户发送 GitLab Commit URL，AI 自动触发代码审查流程。

## 触发条件

### URL 格式
```
https://<domain>/<project-path>/-/commit/<sha>
```

### 触发规则
1. **URL + 关键词**：`review`、`审查`、`审核`、`检查`、`看看`、`帮我看`
2. **仅 URL**：消息只包含 commit URL，自动触发
3. **排除规则**：包含 `不要审查`、`别审查` 时不触发

## 对话示例

### 自动触发
```
用户：@gemini https://gitlab.example.com/project/-/commit/abc123
Gemini：🔍 正在审查提交 abc123...
        
        ## 代码审查报告
        
        **变更摘要**
        - 修改了 3 个文件
        - 新增 45 行，删除 12 行
        
        **问题发现**
        1. ⚠️ SQL 注入风险...
        2. 💡 建议优化...
```

### 带关键词
```
用户：@gemini 帮我看看这个提交 https://gitlab.example.com/project/-/commit/abc123
Gemini：🔍 正在审查提交 abc123...
        [审查报告]
```

### 不触发
```
用户：@gemini 这个提交的链接是 https://gitlab.example.com/project/-/commit/abc123，但不要审查，只是记录一下
Gemini：好的，已记录该提交链接。
```

## 多轮对话示例

### 审查后追问
```
用户：@gemini https://gitlab.example.com/project/-/commit/abc123
Gemini：[审查报告：发现 SQL 注入风险...]

用户：@gemini 这个 SQL 注入具体是什么问题？
Gemini：在您提交的代码中，第 42 行使用了字符串拼接来构建 SQL 查询...
        建议使用参数化查询...

用户：@gemini 能给个修改示例吗？
Gemini：当然，这是修改后的代码：
        ```python
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        ```
```

### 连续审查多个提交
```
用户：@gemini https://gitlab.example.com/project/-/commit/abc123
Gemini：[审查报告 1]

用户：@gemini 这个呢？ https://gitlab.example.com/project/-/commit/def456
Gemini：[审查报告 2]

用户：@gemini 这两个提交有什么关联吗？
Gemini：根据审查结果，这两个提交似乎是相关的：
        - 提交 abc123 添加了用户认证功能
        - 提交 def456 修复了认证逻辑的一个 bug...
```

## 代码审查 Flow

### 架构
```
用户消息
    │
    ▼
┌─────────────────┐
│ 检测 GitLab URL │
│ 检测触发关键词  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CodeReviewFlow  │
│ (CrewAI Agent)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌────────┐
│获取   │ │获取    │
│Commit │ │Diff    │
│Info   │ │Content │
└───┬───┘ └───┬────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│ LLM 分析代码    │
│ 生成审查报告    │
└────────┬────────┘
         │
         ▼
    审查报告
```

### Agent 配置
```python
code_review_agent = Agent(
    role="代码审查专家",
    goal="发现代码中的问题和改进点",
    backstory="资深代码审查员，熟悉安全、性能、可维护性等方面",
)
```

## 上下文保存

```python
# 审查报告保存为助手消息
context_manager.add_message(
    chat_id=chat_id,
    content=review_report,
    role="assistant",
    bot_type=bot_type,
)
```

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 触发方式 | URL 检测 + 关键词 | 显式 /review 命令 |
| 审查深度 | 自动判断 | 可配置层级 |
| 报告格式 | Markdown 文本 | HTML 文件 |
| 历史关联 | 保存到上下文 | 独立审查记录 |

## 待考虑

1. **私有仓库认证**：如何安全处理 GitLab Token？
2. **大型提交**：超过 1000 行的改动如何处理？
3. **审查模板**：是否需要支持自定义审查模板？
