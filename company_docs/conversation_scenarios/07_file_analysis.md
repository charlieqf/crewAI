# 场景 07：文件分析（PDF/图片）

## 场景描述

用户发送文件（PDF、图片等），AI 分析文件内容并回答问题。

## 支持的文件类型

| 类型 | Gemini | ChatGPT | Grok |
|-----|--------|---------|------|
| PDF | ✅ | ❌ | ❌ |
| 图片 | ✅ | ✅ | ✅ |
| 文档 | ✅ | ❌ | ❌ |

## 对话示例

### PDF 分析
```
用户：[发送 PDF 文件: 财务报告.pdf]
用户：@gemini 这份报告的主要内容是什么？
Gemini：这是一份 2024 年第三季度财务报告，主要内容包括：
        1. 营收同比增长 15%
        2. 净利润达到 XXX 万元
        3. ...

用户：@gemini 第三季度的主要支出项目有哪些？
Gemini：根据报告第 12 页，第三季度主要支出包括：
        1. 研发投入：XXX 万元（占比 30%）
        2. 市场营销：XXX 万元（占比 20%）
        ...
```

### 图片分析
```
用户：[发送截图: 错误页面.png]
用户：@gemini 这个错误是什么原因？
Gemini：从截图中可以看到 HTTP 500 错误...
        这通常是服务器内部错误，可能的原因：
        1. 数据库连接失败
        2. 代码异常未捕获
        ...
```

### 多图分析
```
用户：[发送图片 1: UI设计稿-首页.png]
用户：[发送图片 2: UI设计稿-详情页.png]
用户：@gemini 这两个页面的设计风格一致吗？

Gemini：分析这两个设计稿：
        
        **一致性分析**
        - 色彩体系：两个页面都使用蓝色主色调 ✅
        - 字体：标题使用思源黑体 ✅
        - 间距：详情页间距略大，建议统一 ⚠️
        ...
```

## 文件上下文机制

### 文件保存
```python
# 用户发送文件时
context_manager.save_file(
    chat_id=chat_id,
    sender_id=user_id,
    sender_name=user_name,
    file_uri="base64:...",    # 或云端 URI
    filename="财务报告.pdf",
    mime_type="application/pdf",
    wecom_msg_id=msg_id,      # 用于引用匹配
)
```

### 10 分钟自动上下文
```python
# 检查最近 10 分钟内的文件
file_ctx = context_manager.get_active_file(chat_id, limit=50)

if file_ctx:
    elapsed_minutes = (time.time() - file_ctx["timestamp"]) / 60
    if elapsed_minutes > 10:
        file_ctx = None  # 超过 10 分钟，忽略
```

### 引用特定文件
```
用户：[引用之前发送的 PDF]
用户：@gemini 总结这个文档
# 明确引用，即使超过 10 分钟也会使用
```

## 多轮文件对话

### 持续追问
```
用户：[发送 PDF]
用户：@gemini 总结一下

Gemini：这是一份关于...的文档

用户：@gemini 第三章讲了什么？
# 10 分钟内，自动使用同一文件
Gemini：第三章主要讨论了...

[等待 15 分钟]

用户：@gemini 那第四章呢？
# 超过 10 分钟，文件上下文已过期
Gemini：你好！请先发送需要分析的文档，或引用之前的文件消息。
```

### 切换文件
```
用户：[发送 文件A.pdf]
用户：@gemini 总结文件A
Gemini：文件A 是一份...

用户：[发送 文件B.pdf]
用户：@gemini 总结文件B
Gemini：文件B 是一份...

用户：@gemini 文件A 和文件B 有什么区别？
# 只有文件B 在自动上下文内
# 文件A 需要通过引用来访问

用户：[引用文件A的消息]
用户：@gemini 比较一下这两个文件
Gemini：对比分析：
        - 文件A：...
        - 文件B：...
```

## LLM 调用方式

### Gemini - 原生文件支持
```python
response = router.chat_with_file(
    provider="gemini",
    text="总结这个文档",
    file_data=file_bytes,
    file_mime_type="application/pdf",
    filename="文档.pdf",
    history=history_messages,
    system_prompt=system_prompt,
)
```

### OpenAI - 图片 Vision
```python
# 仅支持图片，不支持 PDF
response = router.chat(
    provider="openai",
    messages=[
        {"role": "user", "content": [
            {"type": "text", "text": "描述这张图片"},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]}
    ]
)
```

## 关键决策

| 决策点 | 当前方案 | 备选方案 |
|-------|---------|---------|
| 自动上下文有效期 | 10 分钟 | 可配置 |
| 文件存储 | Base64 或云端 URI | 统一云存储 |
| 多文件支持 | 最近 1 个 | 支持多文件同时分析 |
| 不支持的格式 | 静默忽略 | 提示用户 |

## 待考虑

1. **大文件处理**：超过 10MB 的文件如何处理？
2. **文件预处理**：是否需要 OCR、文本提取？
3. **多文件上下文**：同时保持多个文件的上下文？
