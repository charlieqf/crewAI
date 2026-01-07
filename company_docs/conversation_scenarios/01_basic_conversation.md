# 场景 01：基础多轮对话

## 场景描述

用户与 AI 进行普通的多轮对话，无特殊指令或文件。

## 对话示例

```
用户：@gemini 你好，我想了解一下Python的装饰器
Gemini：你好！Python装饰器是一种...（解释）

用户：@gemini 能给个例子吗？
Gemini：当然，这是一个简单的例子...（代码示例）

用户：@gemini 那多个装饰器的执行顺序是怎样的？
Gemini：多个装饰器从下往上执行...（解释）
```

## 上下文管理

### 消息存储
- 每条消息保存到 SQLite 数据库
- 字段：`chat_id`, `sender_id`, `sender_name`, `content`, `role`, `timestamp`

### 上下文构建
```python
# 每次 LLM 调用时
messages = [
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "user", "content": "你好，我想了解一下Python的装饰器"},
    {"role": "assistant", "content": "你好！Python装饰器是一种..."},
    {"role": "user", "content": "能给个例子吗？"},
    {"role": "assistant", "content": "当然，这是一个简单的例子..."},
    {"role": "user", "content": "那多个装饰器的执行顺序是怎样的？"},  # 当前消息
]
```

### 限制策略
- **max_messages = 20**：最多保留 20 条历史消息
- **max_chars = 8000**：最多 8000 字符
- 超出限制时，从最早的消息开始移除

## 关键代码

```python
# chat_context.py
class ChatContextManager:
    def get_messages_for_llm(self, chat_id, system_prompt=None):
        # 从数据库获取历史消息
        # 应用滑动窗口限制
        # 格式化为 LLM 消息格式
        pass
```

## 预期行为

| 用户操作 | 系统行为 |
|---------|---------|
| 发送普通消息 | 保存到上下文 → 构建完整消息列表 → 调用 LLM → 保存回复 |
| 连续对话 | 每次都能访问之前的对话历史 |
| 超过 20 条消息 | 自动移除最早的消息 |

## 注意事项

1. **响应不应包含文件**：普通对话不生成 `<FILE>` 标签
2. **System Prompt 干净**：不包含任何文件生成指令
3. **上下文按群聊隔离**：不同 `chat_id` 完全独立
