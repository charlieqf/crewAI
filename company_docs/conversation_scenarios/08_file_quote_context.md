# 场景 08：文件引用与上下文

## 场景描述

用户通过 Quote（引用）功能明确指定要分析的文件，覆盖自动上下文。

## Quote 机制

### 企业微信消息引用
```json
{
  "msgtype": "text",
  "text": {
    "content": "@gemini 分析这个文件"
  },
  "quote": {
    "quoted_content": "财务报告.pdf",
    "quoted_msg_id": "msg_12345"
  }
}
```

### 引用匹配逻辑
```python
# 1. 尝试按 msg_id 匹配
file_ctx = context_manager.get_active_file(
    chat_id, 
    wecom_msg_id=quoted_msg_id
)

# 2. 回退：按文件名匹配
if not file_ctx:
    file_ctx = context_manager.get_active_file(
        chat_id, 
        filename=quoted_filename
    )
```

## 对话示例

### 引用过期文件
```
[1 小时前]
用户：[发送 PDF: 项目计划.pdf]
用户：@gemini 总结这个文档
Gemini：这是一份项目计划...

[现在]
用户：对，就是这个文件
用户：[引用之前的 PDF 消息]
用户：@gemini 这个项目的里程碑有哪些？
# 即使超过 10 分钟，通过引用仍可访问
Gemini：根据《项目计划》，主要里程碑包括：
        1. 需求阶段：3 月底
        2. 设计阶段：4 月中
        ...
```

### 引用特定消息
```
用户：[发送 图片A: 原型图.png]
用户：@gemini 这个设计怎么样？
Gemini：这个设计布局清晰...

用户：[发送 图片B: 最终稿.png]
用户：@gemini 这个版本更好
Gemini：是的，最终稿有这些改进...

用户：[引用图片A消息]
用户：@gemini 对比第一版，有哪些改动？
# 明确引用图片A，同时图片B在自动上下文中
Gemini：对比两个版本：
        - 图片A（原型图）：基础布局...
        - 图片B（最终稿）：添加了颜色...
```

### 引用文字消息
```
用户：我们公司的 Logo 是金色盾牌，品牌色是深蓝
Gemini：好的，记录了

[多轮对话后]

用户：[引用之前关于 Logo 的消息]
用户：@gemini /file-html 做个符合这个品牌的页面
Gemini：云端链接: http://.../branded_page.html
# 引用的文字消息内容被包含在上下文中
```

## 引用优先级

```
引用文件 (Quote)  →  优先级最高
       ↓
自动上下文文件 (10分钟内)  →  次优先
       ↓
无文件上下文  →  纯文本对话
```

## 代码实现

### 引用内容提取
```python
def _extract_quote_content(data: dict) -> tuple[str | None, str | None]:
    """提取引用消息内容和消息ID"""
    quote = data.get("quote", {})
    quoted_content = quote.get("quoted_content")
    quoted_msg_id = quote.get("quoted_msg_id")
    return quoted_content, quoted_msg_id
```

### 融合上下文
```python
# 引用的内容会被添加到用户消息中
if quoted_content:
    if original_content:
        content = f"[用户引用消息: {quoted_content}]\n\n用户提问: {original_content}"
    else:
        content = f"用户引用了以下消息并@你，请针对引用内容回复:\n\n{quoted_content}"
```

## 边界情况

### 引用已删除的文件
```
用户：[引用一个已过期的文件]
用户：@gemini 分析这个

# 文件在服务器上已清理
Gemini：抱歉，该文件可能已过期或不可用。请重新发送文件。
```

### 引用其他人的消息
```
同事A：[发送文件]
同事A：@gemini 看看这个

用户：[引用同事A的文件消息]
用户：@gemini 帮我也分析一下
# 引用跨用户，但在同一群聊内，可以访问
Gemini：根据文件分析...
```

### 引用 Bot 的回复
```
用户：@gemini 写一段代码
Gemini：```python def foo(): pass ```

用户：[引用 Gemini 的回复]
用户：@gemini 解释一下这段代码
Gemini：这段代码定义了一个名为 foo 的函数...
```

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 引用匹配 | msg_id 优先，文件名回退 | 仅 msg_id |
| 过期文件 | 无法访问 | 重新下载 |
| 跨用户引用 | 同群允许 | 仅本人文件 |
| 引用格式 | 添加到消息内容 | 独立上下文 |

## 待考虑

1. **引用链**：引用的消息本身也是引用怎么处理？
2. **批量引用**：同时引用多条消息？
3. **引用预览**：引用内容的预览如何生成？
