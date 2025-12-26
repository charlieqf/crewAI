# WeCom 消息处理链路与故障排查指南

本文档描述企业微信消息从用户发送到机器人回复的完整处理流程、日志标签说明及故障排查方法。

## 目录

1. [消息处理链路](#消息处理链路)
2. [日志标签速查](#日志标签速查)
3. [日志示例](#日志示例)
4. [故障排查指南](#故障排查指南)
5. [常见问题解决](#常见问题解决)

---

## 消息处理链路

当用户在企业微信群里 @机器人 发消息时，完整处理链路如下：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              消息处理链路                                     │
└─────────────────────────────────────────────────────────────────────────────┘

 ┌──────────────┐
 │  企业微信群   │
 │  用户发送:    │
 │ "@gemini 你好"│
 └──────┬───────┘
        │
        ▼ (1) HTTP POST
 ┌──────────────────────────────────────────────────────────────────┐
 │  企业微信服务器                                                    │
 │  加密 XML 消息体                                                   │
 └──────────────────────────────────────────────────────────────────┘
        │
        ▼ (2) HTTPS POST /wecom/callback
 ┌──────────────────────────────────────────────────────────────────┐
 │  Kamatera VM (104.238.213.119:8000)                              │
 │  ┌────────────────────────────────────────────────────────────┐  │
 │  │  wecom_callback.py                                         │  │
 │  │                                                            │  │
 │  │  (3) 验证签名 + 解密 AES                                    │  │
 │  │      ↓                                                     │  │
 │  │  (4) 解析 XML → WeComMessage                               │  │
 │  │      ↓                                     ┌──────────┐    │  │
 │  │  (5) 日志: [RECV]                          │ 日志文件  │    │  │
 │  │      ↓                                     │          │    │  │
 │  │  (6) 路由决策 detect_bot_type()   ───────▶ │ [ROUTE]  │    │  │
 │  │      ↓                                     │          │    │  │
 │  │  (7) 检查清空命令?                          │ [CLEAR]  │    │  │
 │  │      │                                     │          │    │  │
 │  │      ├─(是)→ 清空上下文 ──────────────────▶ │          │    │  │
 │  │      │                                     │          │    │  │
 │  │      └─(否)→ 继续处理                       │          │    │  │
 │  │              ↓                             │          │    │  │
 │  │  (8) 日志: [PROCESS]             ─────────▶│ [PROCESS]│    │  │
 │  │              ↓                             └──────────┘    │  │
 │  └──────────────┼─────────────────────────────────────────────┘  │
 │                 ↓                                                │
 │  ┌────────────────────────────────────────────────────────────┐  │
 │  │  text_handler.py                                           │  │
 │  │                                                            │  │
 │  │  (9) 获取历史上下文 (SQLite)                                │  │
 │  │      ↓                                                     │  │
 │  │  (10) 存储用户消息                                          │  │
 │  │      ↓                                                     │  │
 │  │  (11) 日志: [LLM_REQ]                                       │  │
 │  │      ↓                                                     │  │
 │  │  (12) 调用 LLM API (Gemini/GPT/Grok) ────────────────┐     │  │
 │  │                                                      │     │  │
 │  └──────────────────────────────────────────────────────┼─────┘  │
 └─────────────────────────────────────────────────────────┼────────┘
                                                           │
                                                           ▼ (13) HTTPS
                                              ┌────────────────────────┐
                                              │  LLM Provider API      │
                                              │  (Gemini/OpenAI/xAI)   │
                                              └────────────┬───────────┘
                                                           │
                                                           ▼ (14) 响应
 ┌─────────────────────────────────────────────────────────────────────┐
 │  Kamatera VM                                                        │
 │  ┌────────────────────────────────────────────────────────────┐     │
 │  │  text_handler.py (继续)                                    │     │
 │  │                                                            │     │
 │  │  (15) 日志: [LLM_RES] (记录响应时间和内容)                   │     │
 │  │      ↓                                                     │     │
 │  │  (16) 存储助手响应到数据库                                   │     │
 │  │      ↓                                                     │     │
 │  │  (17) 发送 Webhook 到企业微信群                             │     │
 │  │      ↓                                                     │     │
 │  │  (18) 日志: [SENT]                                         │     │
 │  └────────────────────────────────────────────────────────────┘     │
 └─────────────────────────────────────────────────────────────────────┘
        │
        ▼ (19) HTTP POST Webhook
 ┌──────────────────────────────────────────────────────────────────┐
 │  企业微信群机器人 Webhook                                         │
 └──────────────────────────────────────────────────────────────────┘
        │
        ▼ (20) 消息推送
 ┌──────────────┐
 │  企业微信群   │
 │  显示回复:    │
 │ "@张三 你好！ │
 │  我是Gemini..."│
 └──────────────┘
```

### 关键组件说明

| 组件 | 文件 | 职责 |
| :--- | :--- | :--- |
| 回调入口 | `wecom_callback.py` | 接收消息、解密、路由 |
| 文本处理器 | `text_handler.py` | LLM 调用、响应发送 |
| 文件处理器 | `file_handler.py` | 文件消息处理 |
| 消息解析 | `wecom_message.py` | XML 解析 |
| 加密解密 | `wecom_crypto.py` | AES 加解密 |
| 上下文管理 | `chat_context.py` | 会话历史管理 |
| 存储 | `chat_storage_tool.py` | SQLite/Redis 存储 |

---

## 日志标签速查

### 消息接收阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[RECV]` | 收到 WeCom 回调 | msg_id, type, from, agent, content | `[RECV] msg_id=123 type=text from=张三 content='@gemini 你好'...` |

### 路由决策阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[ROUTE]` | 确定处理路径 | chat_id, user, bot_type | `[ROUTE] chat_id=group123 user=张三 bot_type=gemini` |
| `[NO_WEBHOOK]` | 无可用 Webhook | bot_type, env_key | `[NO_WEBHOOK] bot=gpt env=WEBHOOK_GPT` |
| `[CLEAR]` | 清空命令 | chat_id, user | `[CLEAR] chat_id=group123 user=张三` |
| `[SKIP]` | 跳过处理 | msg_id, type | `[SKIP] msg_id=123 type=event (no handler)` |

### 消息处理阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[PROCESS]` | 开始处理文本 | msg_id, bot, chat_id | `[PROCESS] msg_id=123 bot=gemini chat=group123` |
| `[FILE]` | 处理文件消息 | msg_id, media_id, filename | `[FILE] msg_id=456 media_id=xxx filename=doc.pdf` |

### LLM 调用阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[LLM_REQ]` | 发送 LLM 请求 | bot, provider, chat, user, msg_count, content | `[LLM_REQ] bot=gemini provider=gemini msg_count=5 content='你好'...` |
| `[LLM_RES]` | 收到 LLM 响应 | bot, elapsed_ms, response_len, content | `[LLM_RES] bot=gemini elapsed=1234ms response_len=150 content='你好！'...` |
| `[LLM_ERR]` | LLM 调用失败 | bot, chat, user, error | `[LLM_ERR] bot=gemini chat=group123 error=API key invalid` |

### 响应发送阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[SENT]` | 成功发送回复 | bot, chat, user, elapsed_total | `[SENT] bot=gemini chat=group123 elapsed_total=1523ms` |
| `[WEBHOOK_ERR]` | Webhook 发送失败 | bot, chat, webhook, error | `[WEBHOOK_ERR] bot=gemini webhook=https://... error=timeout` |

### 错误阶段

| 标签 | 触发时机 | 包含信息 | 示例 |
| :--- | :--- | :--- | :--- |
| `[FATAL]` | 未预期的严重错误 | bot, chat, user, error + 堆栈 | `[FATAL] bot=gemini chat=group123 error=...` |

---

## 日志示例

### 正常消息处理流程

```log
2025-12-26 15:30:01 | INFO     | wecom_callback | [RECV] msg_id=7854123456 type=text from=张三 agent=1000001 content='@gemini 今天天气怎么样'...
2025-12-26 15:30:01 | INFO     | wecom_callback | [ROUTE] chat_id=ww_group_abc123 user=张三 bot_type=gemini
2025-12-26 15:30:01 | INFO     | wecom_callback | [PROCESS] msg_id=7854123456 bot=gemini chat=ww_group_abc123
2025-12-26 15:30:01 | INFO     | text_handler   | [LLM_REQ] bot=gemini provider=gemini chat=ww_group_abc123 user=张三 msg_count=3 content='今天天气怎么样'...
2025-12-26 15:30:03 | INFO     | text_handler   | [LLM_RES] bot=gemini elapsed=1523ms response_len=89 content='今天北京天气晴朗...'...
2025-12-26 15:30:03 | INFO     | text_handler   | [SENT] bot=gemini chat=ww_group_abc123 user=张三 elapsed_total=1523ms
```

### 清空上下文命令

```log
2025-12-26 15:35:00 | INFO     | wecom_callback | [RECV] msg_id=7854123457 type=text from=张三 agent=1000001 content='/清空'...
2025-12-26 15:35:00 | INFO     | wecom_callback | [ROUTE] chat_id=ww_group_abc123 user=张三 bot_type=gpt
2025-12-26 15:35:00 | INFO     | wecom_callback | [CLEAR] chat_id=ww_group_abc123 user=张三
2025-12-26 15:35:00 | INFO     | text_handler   | Context cleared for ww_group_abc123
```

### LLM API 错误

```log
2025-12-26 15:40:00 | INFO     | wecom_callback | [RECV] msg_id=7854123458 type=text from=李四 agent=1000001 content='@gpt 帮我写代码'...
2025-12-26 15:40:00 | INFO     | wecom_callback | [ROUTE] chat_id=ww_group_abc123 user=李四 bot_type=gpt
2025-12-26 15:40:00 | INFO     | wecom_callback | [PROCESS] msg_id=7854123458 bot=gpt chat=ww_group_abc123
2025-12-26 15:40:00 | INFO     | text_handler   | [LLM_REQ] bot=gpt provider=openai chat=ww_group_abc123 user=李四 msg_count=1 content='帮我写代码'...
2025-12-26 15:40:01 | ERROR    | text_handler   | [LLM_ERR] bot=gpt chat=ww_group_abc123 user=李四 error=RateLimitError: You exceeded your current quota
```

### Webhook 配置缺失

```log
2025-12-26 15:45:00 | INFO     | wecom_callback | [RECV] msg_id=7854123459 type=text from=王五 agent=1000001 content='@grok 你好'...
2025-12-26 15:45:00 | INFO     | wecom_callback | [ROUTE] chat_id=ww_group_abc123 user=王五 bot_type=grok
2025-12-26 15:45:00 | WARNING  | wecom_callback | [NO_WEBHOOK] bot=grok env=WEBHOOK_GROK not configured
```

---

## 故障排查指南

### 排查流程

按以下顺序检查，找到问题点：

```
消息无响应
    │
    ├── 1. 检查 [RECV] 日志
    │       │
    │       ├── 有 → 消息已收到，继续检查
    │       │
    │       └── 无 → 企业微信配置问题
    │               • 回调 URL 是否正确
    │               • Token/AESKey 是否匹配
    │               • 服务是否运行
    │
    ├── 2. 检查 [ROUTE] 日志
    │       │
    │       ├── 有 → 路由成功，继续检查
    │       │
    │       └── 无 → 消息解密或解析失败
    │               • 检查 ERROR 日志
    │
    ├── 3. 检查 [NO_WEBHOOK]
    │       │
    │       ├── 有 → Webhook 未配置
    │       │       • 设置 WEBHOOK_GPT/GEMINI/GROK
    │       │
    │       └── 无 → 继续检查
    │
    ├── 4. 检查 [LLM_REQ] / [LLM_RES]
    │       │
    │       ├── 只有 REQ 无 RES → LLM 超时或失败
    │       │       • 检查 [LLM_ERR]
    │       │       • 检查 API Key
    │       │
    │       └── 都有 → LLM 正常，继续检查
    │
    ├── 5. 检查 [SENT]
    │       │
    │       ├── 有 → 消息已发送，可能是企业微信延迟
    │       │
    │       └── 无 → 检查 [WEBHOOK_ERR]
    │
    └── 6. 检查 [WEBHOOK_ERR] / [FATAL]
            │
            └── 查看具体错误信息
```

### 常用排查命令

```powershell
# 设置环境变量
$env:KAMATERA_HOST = "104.238.213.119"
$env:KAMATERA_KEY = "$env:USERPROFILE\.ssh\kamatera"

# 1. 服务是否正常运行
python scripts\ops_logs.py status

# 2. 查看最近的消息接收
python scripts\ops_logs.py search "[RECV]" -n 20

# 3. 查看路由决策
python scripts\ops_logs.py search "[ROUTE]" -n 20

# 4. 查看 LLM 调用情况
python scripts\ops_logs.py llm -n 20

# 5. 查看所有错误
python scripts\ops_logs.py errors

# 6. 搜索特定用户
python scripts\ops_logs.py search "张三" -n 50

# 7. 搜索特定群
python scripts\ops_logs.py search "group_abc123" -n 50

# 8. 实时监控日志
python scripts\ops_logs.py tail
```

---

## 常见问题解决

### 问题 1: 消息完全没有响应

**症状**: 发送消息后，机器人没有任何回复

**排查步骤**:

```powershell
# 检查服务状态
python scripts\ops_logs.py status

# 如果服务未运行
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "systemctl start wecom-callback"
```

**可能原因**:
- 服务未启动
- 企业微信回调 URL 配置错误
- Token/AESKey 配置错误

---

### 问题 2: 收到消息但没有回复

**症状**: 有 `[RECV]` 日志但没有 `[SENT]`

**排查步骤**:

```powershell
# 检查是否有 Webhook 配置问题
python scripts\ops_logs.py search "[NO_WEBHOOK]"

# 检查 LLM 错误
python scripts\ops_logs.py llm
```

**可能原因**:
- Webhook URL 未配置 (检查 `WEBHOOK_GPT`, `WEBHOOK_GEMINI`, `WEBHOOK_GROK`)
- LLM API Key 无效或过期
- LLM 服务超时

---

### 问题 3: LLM 响应很慢

**症状**: `[LLM_RES]` 显示 elapsed > 5000ms

**排查步骤**:

```powershell
# 检查 LLM 响应时间
python scripts\ops_logs.py llm -n 50
```

**可能原因**:
- 消息历史太长 (检查 `msg_count`)
- LLM 服务繁忙
- 网络延迟

**解决方案**:
- 用户发送 `/清空` 清理历史
- 调整 `max_recent_messages` 配置

---

### 问题 4: 只有特定机器人不响应

**症状**: @gemini 有响应，@gpt 没响应

**排查步骤**:

```powershell
# 检查特定机器人的 Webhook
python scripts\ops_logs.py search "bot=gpt"

# 检查环境配置
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "grep WEBHOOK /etc/wecom-callback/env"
```

**可能原因**:
- 该机器人的 Webhook URL 未配置
- 该机器人的 API Key 无效

---

### 问题 5: 清空命令不生效

**症状**: 发送 `/清空` 没有清空上下文

**排查步骤**:

```powershell
# 检查清空命令日志
python scripts\ops_logs.py search "[CLEAR]"
```

**可能原因**:
- 命令格式不正确 (支持: `/clear`, `/reset`, `/清空`, `清空记忆`, `忘记之前的`)
- 消息中包含其他内容

---

### 问题 6: 重复消息

**症状**: 机器人对同一条消息回复多次

**排查步骤**:

```powershell
# 检查同一 msg_id 是否被处理多次
python scripts\ops_logs.py search "msg_id=具体ID"
```

**可能原因**:
- 企业微信重试机制 (服务响应慢于 5 秒)
- 去重机制失效

**解决方案**:
- 确保服务快速返回 200 (当前使用 BackgroundTasks)
- 检查 `wecom_msg_id` 唯一索引是否正常

---

*文档更新时间: 2025-12-26*
