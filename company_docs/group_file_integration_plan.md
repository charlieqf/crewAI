# 群聊文件集成方案

## 决策摘要

**当前方案：Smart File Context（智能文件上下文）** ✅

基于多方案评估，我们决定采用轻量级的上下文管理方案，而**不采用**Group Bot或会话存档API。

---

## 方案对比

### 方案 A：Smart File Context（已实施）✅

**原理：** 用户Quote文件 + 10分钟自动上下文窗口

**优势：**
- ✅ **零成本** - 无需付费
- ✅ **已实现** - 无需额外开发
- ✅ **易用** - 用户体验好（Quote即可）
- ✅ **可靠** - 基于现有稳定功能

**实现：**
```
用户发送/Quote文件 → 上传七牛云 → 保存到chat_files表
              ↓
用户@gemini提问（10分钟内）→ 自动关联最新文件上下文
              OR
用户Quote文件 + @gemini → 即时获取文件
```

**功能：**
1. ✅ Quote文件即刻分析
2. ✅ 10分钟自动上下文（无需Quote）
3. ✅ `/new`命令清除上下文
4. ✅ Provider能力检测（ChatGPT/Grok不支持文件）

---

### 方案 B：Group Bot（已放弃）❌

**原理：** 创建群机器人自动收集所有文件

**为什么放弃：**
- ❌ **Group Bot限制** - 企业微信群bot无法接收普通消息
- ❌ **需要应用bot** - 创建应用bot更复杂
- ❌ **开发成本高** - 需要7小时开发 + 配置
- ⚠️ **增值有限** - 相比Quote方案只是稍微方便

**评估结果：** 投入产出比低，不值得实施

---

### 方案 C：会话存档API（已放弃）❌

**原理：** 使用企业微信官方会话存档获取所有消息和文件

**优势：**
- ✅ **有官方SDK** - C SDK（版本20250205）
- ✅ **功能完整** - 获取所有消息、文件、媒体
- ✅ **技术可行** - Python绑定 + 2天开发

**为什么放弃：**
- ❌ **需要付费** - 存档服务费用（可能几百到几千/月）
- ❌ **持续成本** - 维护服务器、处理消息、存储
- ⚠️ **功能过剩** - 只为了不用Quote，太重了

**评估结果：** 成本太高，当前需求不值得

**技术评估记录：**
- SDK位置：`company_docs/C_sdk/`
- 核心API：GetChatData（拉取消息）、DecryptData（解密）、GetMediaData（下载文件）
- 实施工作量：14小时（Python绑定+集成+测试）
- 但因成本原因暂不实施

---

## 当前实现细节

### 1. Smart File Context架构

```
文件处理流程：
┌─────────────────────┐
│ 用户上传/Quote文件  │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────┐
│  aibot_callback.py      │
│  _handle_file_upload    │
│  1. 下载企微文件        │
│  2. 上传七牛云          │
│  3. 保存chat_files表    │
│  4. 记录上传时间        │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────────────┐
│        SQLite chat_files         │
│  - wecom_msg_id (索引)           │
│  - file_uri (Qiniu URL)          │
│  - upload_time (时间戳)          │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  用户 @gemini 提问               │
│                                  │
│  场景1：Quote文件 → 即时获取    │
│  场景2：10分钟内 → 自动关联     │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  _call_llm_async                 │
│  - 检查quoted_msg_id             │
│  - 或检查10分钟窗口             │
│  - 下载文件 → 传给LLM           │
└──────────────────────────────────┘
```

---

### 2. 10分钟时间窗口逻辑

```python
# 代码位置：src/crewai_enterprise/server/aibot_callback.py

# 检查是否在10分钟窗口内
file_context = None
latest_file = context_manager.get_latest_file(chat_id)

if latest_file:
    upload_time = latest_file['upload_time']
    current_time = int(time.time())
    time_diff_minutes = (current_time - upload_time) / 60
    
    # 10分钟内自动使用
    if time_diff_minutes <= 10:
        file_context = latest_file
        logger.info(f"[FILE_CTX] Using file within 10min window")
    else:
        logger.info(f"[FILE_CTX] File too old ({time_diff_minutes:.1f}min)")
```

**设计决策：**
- ⏱️ **10分钟** - 平衡便利性和精确度
- 🔄 **可配置** - 可以改为5分钟或15分钟
- 🆕 **可清除** - `/new`命令重置上下文

---

### 3. Provider能力检测

```python
# 配置位置：src/crewai_enterprise/server/aibot_callback.py

BOT_CONFIGS = {
    "gemini": {
        ...,
        "supports_file_analysis": True  # ✅ Gemini支持
    },
    "chatgpt": {
        ...,
        "supports_file_analysis": False  # ❌ ChatGPT不支持
    },
    "grok": {
        ...,
        "supports_file_analysis": False  # ❌ Grok不支持
    }
}

# 调用时检查
if not bot_config.get("supports_file_analysis", False):
    file_context = None
    logger.info(f"[FILE_CTX] {bot_type} doesn't support file analysis")
```

---

### 4. `/new`命令

```python
# 命令处理：src/crewai_enterprise/server/aibot_callback.py

elif command == "new":
    # 清除文件上下文
    success = context_manager.clear_file_context(chat_id)
    if success:
        response = "✅ 已清除文件上下文，开始新对话..."
```

**用途：**
- 🧹 清除旧文件的干扰
- 🆕 开始新话题
- 🎯 精确控制上下文

---

## 用户使用指南

### 场景1：Quote文件分析（推荐）

```
1. 在群里上传PDF文件
2. Quote该文件并@gemini："这个文件讲了什么？"
3. Gemini立即分析文件内容
```

**优势：** 精确、可靠、支持多个文件

---

### 场景2：10分钟自动上下文

```
1. 在群里上传PDF文件
2. 10分钟内直接@gemini："总结一下"
3. Gemini自动使用最近上传的文件
```

**优势：** 方便、无需Quote

**限制：** 
- 只记忆最新1个文件
- 超过10分钟需要Quote

---

### 场景3：清除上下文

```
用户：@gemini /new
Gemini：✅ 已清除文件上下文，开始新对话...
```

**用途：** 避免旧文件干扰新对话

---

## 技术实现位置

| 功能 | 代码位置 | 说明 |
|------|---------|------|
| 文件上传 | `aibot_callback.py:_handle_file_upload()` | 下载+上传七牛+保存DB |
| Quote检测 | `aibot_callback.py:_call_llm_async()` | 获取quoted_msg_id |
| 10分钟窗口 | `aibot_callback.py:_call_llm_async()` | 时间检查逻辑 |
| /new命令 | `aibot_callback.py:_handle_prompt_command()` | 清除上下文 |
| 数据库操作 | `utils/chat_context.py:ChatContextManager` | 文件CRUD |
| Provider检测 | `aibot_callback.py:BOT_CONFIGS` | 能力标志 |

---

## 为什么这个方案最好？

### 成本效益分析

| 方案 | 开发成本 | 运营成本 | 用户体验 | 可靠性 |
|------|---------|---------|---------|--------|
| **Smart Context** | ✅ 0小时（已完成） | ✅ $0/月 | 😊 很好 | ✅ 高 |
| Group Bot | ❌ 7小时 | ✅ $0/月 | 😃 稍好 | ⚠️ 中 |
| 会话存档 | ❌ 14小时 | ❌ $几百/月 | 😃 稍好 | ✅ 高 |

**结论：** Smart Context提供了90%的便利性，只需要10%的成本。

---

### 用户反馈优化路径

如果未来用户反馈"Quote太麻烦"，可以考虑：

**优先级排序：**
1. ✅ **延长时间窗口** - 10分钟 → 30分钟（5分钟开发）
2. ⚠️ **智能提示** - 检测文件相关问题，提示Quote（1小时开发）
3. ❌ **Group Bot** - 如果上面两个都不够（7小时开发）
4. ❌ **会话存档** - 除非有合规需求（14小时+月费）

---

## 数据库Schema

```sql
-- chat_files表（现有）
CREATE TABLE IF NOT EXISTS chat_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    sender_id TEXT,
    wecom_msg_id TEXT UNIQUE,  -- 用于Quote查找
    filename TEXT NOT NULL,
    file_uri TEXT NOT NULL,     -- 七牛云URL
    upload_time INTEGER NOT NULL,  -- Unix时间戳
    file_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_chat_files_wecom_msg_id ON chat_files(wecom_msg_id);
CREATE INDEX IF NOT EXISTS idx_chat_files_chat_id_time ON chat_files(chat_id, upload_time DESC);
```

---

## 配置参数

```python
# 可配置的常量
FILE_CONTEXT_WINDOW_MINUTES = 10  # 自动上下文时间窗口
MAX_FILE_SIZE_MB = 50              # 最大文件大小
SUPPORTED_FILE_TYPES = [           # 支持的文件类型
    'application/pdf',
    'image/png',
    'image/jpeg',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    # ...
]
```

---

## 监控和日志

**关键日志标记：**
```
[FILE_CTX] - 文件上下文相关
[FILE_UPLOAD] - 文件上传过程
[QINIU] - 七牛云操作
[PROMPT_CMD] - 命令处理
```

**示例日志：**
```
INFO [FILE_UPLOAD] Uploaded file report.pdf to Qiniu
INFO [FILE_CTX] Using file within 10min window: report.pdf
INFO [PROMPT_CMD] Clear file context for chat ww123
```

---

## 未来扩展方向

### 如果用户量增长或需求变化：

**场景1：需要审计/合规**
→ 启用会话存档API
→ 保存所有消息记录
→ 成本：~$500/月 + 14小时开发

**场景2：极致用户体验**
→ 实施Group Bot自动收集
→ 成本：7小时开发

**场景3：企业级文件管理**
→ 构建文件知识库
→ 跨群文件共享
→ 全文搜索
→ 成本：2-3周开发

---

## 总结

**当前方案（Smart File Context）是最优解：**
- ✅ 已经实现并稳定运行
- ✅ 零额外成本
- ✅ 用户体验良好（90%+场景满足）
- ✅ 代码简洁可维护

**暂不采用的方案：**
- ❌ Group Bot - 投入产出比低
- ❌ 会话存档 - 成本高，当前不需要

**决策原则：** 从简到繁，按需扩展

---

**更新时间：** 2026-01-04  
**状态：** 当前方案已生产部署 ✅  
**下次评估：** 根据用户反馈决定
