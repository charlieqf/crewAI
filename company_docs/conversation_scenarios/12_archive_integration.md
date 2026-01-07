# 场景 12：对话存档集成与"深层记忆"

## 场景描述

利用企业微信存档服务（Archive Service）提供的全量历史数据，赋予 Bot "长期记忆"和"全局视野"。

## 架构基础

### 数据流
1. **WeCom Archive API** → **Archive Callback** → **SQLite/Postgres DB** (全量存储)
2. **WeCom Chat Window** → **AIBot Callback** → **LLM** (交互接口)

### 能力差异
- **短期记忆 (Context)**: 最近 20 条消息，存于内存/轻量 DB，用于直接对话流畅性。
- **长期记忆 (Archive)**: 所有历史消息，存于全量 DB，需通过"检索工具"访问。

## 场景 A：历史回溯 (Recall)

用户询问很久以前的信息。

```
用户：@gemini 上周五我们讨论的那个 API Key 是多少？
Gemini：(触发 Archive 搜索工具)
        🔍 搜索时间范围：上周五
        🔍 关键词：API Key
        
        找到以下相关记录：
        [2024-01-05 14:30] 张三：API Key 是 `sk-123456...`
        
        Gemini：根据记录，上周五张三发送的 API Key 是 `sk-123456...`。
```

## 场景 B：自动会议纪要 (Daily Summary)

Bot 自动总结群聊一天的内容。

```
[每天 18:00 定时触发或手动触发]
用户：@gemini 总结通过今天的讨论内容
Gemini：(读取 Archive 今日全量消息)
        
        📅 **今日讨论总结 (2025-01-07)**
        
        **1. 需求评审**
        - 确认了登录页面的设计风格为金融科技风
        - 决定使用 Keycloak作为认证服务
        
        **2. Bug 修复**
        - 修复了 iOS 端图片上传失败的问题 (@李四)
        - 解决了 Archive Callback 的 Token 验证错误 (@王五)
        
        **3. 待办事项**
        - [ ] @张三 明天提交 API 定义文档
```

## 场景 C：项目脉络梳理 (Topic Tracking)

梳理某个话题的完整讨论脉络。

```
用户：@gemini 帮我梳理一下关于 "WeCom 回调" 这个问题的完整解决过程
Gemini：(在 Archive 中搜索 "WeCom 回调" 相关消息并按时间排序)
        
        **WeCom 回调问题处理时间线：**
        
        1. **问题发现 (12-25 10:00)**: @UserA 首次反馈回调 404 错误。
        2. **排查 (12-25 10:30)**: @UserB 发现 Nginx 配置缺少 `/wecom` 路径转发。
        3. **尝试修复 (12-25 11:00)**: 修改 Nginx 配置，但出现 500 错误。
        4. **最终解决 (12-25 14:00)**: 发现是 RSA 私钥路径配置错误，修正后验证通过。
```

## 场景 D：新成员入群 onboarding

新成员加入群聊，快速了解上下文。

```
[新成员入群]
新用户：@gemini 我刚进群，最近大家在聊什么？
Gemini：(获取最近 3 天的 Archive 摘要)
        欢迎！最近 3 天群里主要在讨论：
        1. WeCom Archive 服务的部署和调试
        2. AI Bot 的 `/file-html` 新功能测试
        
        相关的关键文档：
        - `设计稿_v3.png`
        - `api_docs_v2.pdf`
```

## 关键技术点

### 1. 意图识别
Bot 需要识别出用户是在问"历史"（需查询 Archive），还是在问"现在"（仅用 Context）。
- "上周..." → Archive
- "刚才..." → Context
- "总结..." → Archive (通常涉及大量消息)

### 2. 权限边界
- Bot 只能读取其**所在群聊**的 Archive。
- 必须严格遵守企业微信的数据隐私规范。

### 3. 工具化 (Tool Use)
Archive 查询不仅是一个"上下文补充"，更应作为 LLM 的一个 **Tool**。
```python
@tool
def search_archive(query: str, time_range: str, sender: str = None):
    """搜索群聊历史记录"""
    ...
```

1. **Archive Search Tool**: 封装 SQL 查询为 Tool 给 LLM 调用。
2. **Summary Agent**: 专门用于生成日报/周报的后台任务。
3. **Reference Linking**: 在回答中引用具体的历史消息链接（WeCom 协议链接）。

## 数据架构 (Data Architecture)

### 为什么要两个数据库？(Hot vs Cold)

目前系统中存在两套数据库，确实存在数据重叠，但这是有意为之的 **"Lambda 架构"** 设计：

| 数据库 | 角色 | 写入路径 | 特点 | 适用场景 |
| :--- | :--- | :--- | :--- | :--- |
| **chat_storage.db** | **热数据 (Hot)** | 实时 API 回调 (@Bot) | **低延迟**、轻量、仅含相关消息 | 对话上下文保持、秒级回复 |
| **chat_history.db** | **冷数据 (Cold)** | 异步 SDK 拉取 (Archive) | **全量**、包含文件/Schema复杂、延迟较高 | 历史回溯、审计、日报生成 |

**不合并的理由**：
1.  **性能隔离**：Archive 同步涉及大文件下载和解密，容易长事务锁表；Bot 需要毫秒级响应，不能被 Archive 拖慢。
2.  **权限边界**：Bot DB 仅包含用户"显式"与其交互的内容，符合最小权限原则；Archive DB 包含私密历史，访问需严格鉴权。
3.  **生存周期**：Bot Context 是滑动窗口（仅存最近20条）；Archive 是永久存储。
