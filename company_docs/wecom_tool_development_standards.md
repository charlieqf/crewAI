# WeComTool 开发规范与技术方案 (TDD 导向)

本规范定义了 `WeComTool` 的技术实现标准，确保其符合 CrewAI 架构规范，并具备高可靠性。

---

## 1. 接口定义 (Interface Definition)

`WeComTool` 将遵循 CrewAI 的 `BaseTool` 模式，强制执行 Pydantic 数据验证。

### 1.1 输入架构 (Input Schema)
```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, Type

class WeComToolInput(BaseModel):
    """WeComTool 的输入参数规范"""
    content: str = Field(..., description="要发送的消息内容，支持平文或 Markdown（取决于 msg_type）")
    msg_type: Literal["text", "markdown"] = Field(
        default="text", 
        description="消息类型：'text'（纯文本）或 'markdown'（格式化文档）"
    )
    chat_id: Optional[str] = Field(
        None, 
        description="目标群聊 ID。如果未指定，则广播给所有用户"
    )
```

### 1.2 类结构 (Class Structure)
```python
from crewai.tools import BaseTool
from pydantic import PrivateAttr

class WeComTool(BaseTool):
    name: str = "WeCom Notification Tool"
    description: str = "用于向企业微信群推送自动化报告、提醒和复盘摘要。支持 Markdown 格式。"
    args_schema: Type[BaseModel] = WeComToolInput
    
    # 必填配置（建议通过环境变量注入）
    corp_id: str   # 企业 ID (corpid)
    agent_id: str  # 应用 ID (agentid)
    secret: str    # 应用 Secret
    
    # 实例级 Token 缓存（避免跨实例共享）
    _token_cache: Optional[str] = PrivateAttr(default=None)
    
    def _run(self, content: str, msg_type: str = "text", chat_id: Optional[str] = None) -> str:
        """同步执行入口"""
        # 1. 自动维护 Token 逻辑
        # 2. 根据 chat_id 决定使用 chatid (群聊) 或 touser (广播) 字段
        # 3. 调用企业微信 API
        # 4. 返回发送结果 / 抛出 WeComSendError
```

---

## 2. 调用示例 (Usage Examples)

### 2.1 开发者直接调用（本地测试）
```python
wecom = WeComTool(corp_id="ww12345678", agent_id="1000001", secret="abc...")
result = wecom._run(content="# 标题\n内容...", msg_type="markdown", chat_id="group123")
print(result)  # "Message sent successfully"
```

### 2.2 给 Agent 赋能（CrewAI 模式）
```python
from crewai import Agent

auditor = Agent(
    role="代码审计专家",
    goal="评审代码并通知团队",
    backstory="你负责深挖代码中的逻辑 Bug，并通过企业微信实时汇报。",
    tools=[WeComTool(corp_id="ww...", agent_id="...", secret="...")]
)
```

---

## 3. TDD (测试驱动开发) 实施方案

我们将采取 **"先写测试，再写逻辑，后重构"** 的 TDD 模式。

### 3.1 测试策略
- **Mock 外部依赖**：使用 `unittest.mock` 模拟企业微信的 HTTP 响应。禁止在单元测试中发起真实公网请求。
- **断言标准**：
    - 验证 Token 获取成功/失败逻辑。
    - 验证输入参数不合法时的 Pydantic 报错。
    - 验证 `chat_id` 群聊与广播的 Payload 路由正确性。
    - 验证发送失败时抛出 `WeComSendError`。

### 3.2 目录结构
```text
tests/
  tools/
    test_wecom_tool.py
company_docs/
  wecom_tool_development_standards.md
```

---

## 4. 异常处理规范
我们定义了以下专用异常类：

| 异常类 | 触发条件 |
| :--- | :--- |
| `WeComAuthenticationError` | Token 获取失败（如 Secret 错误、corpid 无效） |
| `WeComSendError` | 消息发送失败（如群聊不存在、权限不足） |

- **网络超时**：所有 HTTP 请求设置 `timeout=10` 秒。
- **HTTP 错误**：调用 `raise_for_status()` 捕获非 2xx 响应。

---

## 5. 开发建议
1. **安全性**：`corp_id`、`agent_id` 和 `secret` 必须存储在 `.env` 环境变量中，禁止硬编码。
2. **原子性**：`WeComTool` 仅负责"发声"，不应包含任何业务逻辑判断。
3. **术语统一**：群聊参数统一使用 `chat_id`（与企业微信 API 的 `chatid` 对应）。
