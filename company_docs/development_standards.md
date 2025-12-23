# 开发规范与注意事项 (Code Standards & Best Practices)

本文档整合了本项目的代码规范与开发中常见的易错点，旨在帮助团队成员统一开发风格、避免低级错误、确保代码质量。

---

## 1. Python 代码风格 (PEP 8 & 项目约定)

### 1.1 导入规范 (Imports)
- **所有 `import` 语句必须放在文件顶部**，严禁在函数内部使用 `import`。
- **分组顺序**：
  1. 标准库 (`typing`, `os`, `json` 等)
  2. 第三方库 (`requests`, `pydantic` 等)
  3. 本项目模块 (`crewai.tools`, `src.xxx` 等)

```python
# ✅ 正确
from typing import Optional, Literal, Type

import requests
from pydantic import BaseModel, Field

from crewai.tools import BaseTool

# ❌ 错误 (函数内 import)
def my_function():
    import requests  # 严禁！
```

### 1.2 类型注解 (Type Hints)
- **所有函数参数和返回值** 必须添加类型注解。
- **可选参数** 使用 `Optional[X]` 或 `X | None` (Python 3.10+)。
- **禁止使用裸 `None` 默认值**，必须显式声明类型。

```python
# ✅ 正确
def send_message(content: str, group_id: Optional[str] = None) -> str:
    ...

# ❌ 错误
def send_message(content, group_id=None):  # 缺少类型注解
    ...
```

---

## 2. 文档规范

### 2.1 Markdown 格式一致性
- **分隔线 `---`**：每个主章节后使用一个分隔线，禁止连续使用多个。
- **表格对齐**：表头和内容列需使用 `:---` 进行左对齐。
- **代码块语言标识**：代码块必须显式标注语言（如 `python`, `bash`）。

### 2.2 中英文一致性
- 同一文档中，技术术语的语言应保持一致。
- 如果文档面向中文读者，代码注释可中文；但代码变量名、函数名等必须使用英文。

---

## 3. Pydantic 模型规范

### 3.1 Input Schema 定义
- 所有自定义 Tool 必须定义 `args_schema`。
- 使用 `Literal` 限制枚举类型输入。
- 使用 `Field(...)` 添加描述信息，帮助 Agent 理解参数用途。

```python
class WeComToolInput(BaseModel):
    content: str = Field(..., description="消息内容")
    msg_type: Literal["text", "markdown"] = Field(default="text")
```

### 3.2 敏感字段处理
- 使用 `Field(..., exclude=True)` 将敏感字段（如 `secret`）从序列化输出中排除。

---

## 4. 测试规范

### 4.1 TDD 原则
- **红灯先行**：先写失败的测试用例，再编写实现代码。
- **禁止真实 API 调用**：使用 `unittest.mock` 模拟所有外部 HTTP 请求。

### 4.2 必测场景
每个 Tool 必须包含以下测试用例：
1. **正常流程**：验证成功返回。
2. **参数校验**：验证非法输入被 Pydantic 拦截。
3. **异常处理**：验证 API 返回错误时的处理逻辑。
4. **缓存/刷新机制**：如涉及 Token 等，需验证其刷新逻辑。

### 4.3 Mock 路径注意事项
- `@patch` 的路径应为代码**被调用时**的完整路径，而非定义位置。

```python
# 假设 wecom_tool.py 中调用了 requests.post
# 正确的 mock 路径是：
@patch('src.crewai_enterprise.tools.wecom.wecom_tool.requests.post')

# 而不是：
@patch('requests.post')  # 可能在某些情况下失效
```

---

## 5. 异常处理规范

- **禁止使用通用 `Exception`**：应定义业务相关的异常类（如 `WeComAuthenticationError`）。
- **错误信息必须可追溯**：包含原始 API 返回的 `errcode` 和 `errmsg`。

```python
class WeComAuthenticationError(Exception):
    """企业微信认证失败异常"""
    pass

# 使用示例
if data.get("errcode") != 0:
    raise WeComAuthenticationError(f"Code: {data.get('errcode')}, Msg: {data.get('errmsg')}")
```

---

## 6. Fail Early, Fail Fast 原则

> [!CAUTION]
> **禁止过度防御性编程。** 隐藏问题的代码比暴露问题的代码更危险。

### 6.1 核心理念
- **错误应立即、明确地暴露**，而不是被 fallback 机制静默吞掉。
- **调用方应感知到异常**，而不是收到一个"看起来正常但实际有问题"的默认值。

### 6.2 禁止的模式
```python
# ❌ 禁止：吞掉异常并返回默认值
def get_data():
    try:
        return fetch_from_api()
    except Exception:
        return []  # 问题被隐藏，下游代码以为一切正常

# ❌ 禁止：无限 fallback 链
def get_config():
    return os.getenv("KEY") or config.get("key") or "default"  # 哪个生效了？不知道
```

### 6.3 推荐的模式
```python
# ✅ 推荐：快速失败，明确报错
def get_data():
    response = fetch_from_api()  # 如果失败，直接让异常传播
    if not response.ok:
        raise DataFetchError(f"API returned {response.status_code}")
    return response.json()

# ✅ 推荐：必需配置缺失时立即报错
def get_config():
    value = os.getenv("KEY")
    if not value:
        raise ConfigurationError("Required env var 'KEY' is not set")
    return value
```

### 6.4 例外情况
仅在以下场景允许有限的 fallback：
- **用户体验层**：UI 展示可以 graceful degrade，但后端逻辑必须 fail fast。
- **明确的可选功能**：文档中注明某功能是"尽力而为"的。

---

## 7. Git 提交规范

- **提交前必须运行测试**：`uv run python -m unittest discover tests`
- **Commit Message 格式**：`<type>(<scope>): <subject>`
  - `feat`: 新功能
  - `fix`: Bug 修复
  - `docs`: 文档更新
  - `refactor`: 重构（不改变功能）
  - `test`: 测试相关

---

> [!CAUTION]
> 违反以上规范的代码将在 Code Review 阶段被驳回。请在提交前自查。
