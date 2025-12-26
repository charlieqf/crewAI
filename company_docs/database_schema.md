# 数据库 Schema 设计

> 版本: 2.0  
> 更新: 2025-12-26

## 概述

WeCom Callback 服务使用 **SQLite** 作为消息存储后端，数据库文件路径由 `CHAT_DB_PATH` 环境变量控制（默认：`chat_storage.db`）。

---

## 表结构

### `chat_messages` - 聊天消息表

存储所有接收和发送的消息。

```sql
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,                              -- 内部生成的合成 ID (msg_xxx)
    wecom_msg_id TEXT,                            -- 企微原始 MsgId (用于去重)
    chat_id TEXT NOT NULL,                        -- 群聊/会话标识符
    sender_id TEXT NOT NULL,                      -- 发送者用户 ID
    sender_name TEXT NOT NULL,                    -- 发送者显示名称
    content TEXT NOT NULL,                        -- 消息内容
    role TEXT DEFAULT 'user',                     -- 角色: 'user' 或 'assistant'
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, -- 服务器生成
    message_type TEXT DEFAULT 'text',             -- 消息类型 (text/image/file)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP -- 记录创建时间
);

-- 索引：优化按日期查询
CREATE INDEX IF NOT EXISTS idx_chat_date 
    ON chat_messages(chat_id, DATE(timestamp));

-- 索引：企微消息去重
CREATE UNIQUE INDEX IF NOT EXISTS idx_wecom_msg_id
    ON chat_messages(wecom_msg_id)
    WHERE wecom_msg_id IS NOT NULL;
```

#### 字段说明

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :---: | :--- |
| `id` | INTEGER | ✅ | 自增主键 |
| `message_id` | TEXT | ❌ | 内部生成的合成 ID (`msg_xxx`) |
| `wecom_msg_id` | TEXT | ❌ | 企微原始 MsgId，用于去重，有唯一索引 |
| `chat_id` | TEXT | ✅ | 群聊标识符。**WeCom 回调场景**：使用 `agent_id`。**其他场景**：可传入任意标识符 |
| `sender_id` | TEXT | ✅ | 发送者的企微用户 ID |
| `sender_name` | TEXT | ✅ | 发送者显示名称 |
| `content` | TEXT | ✅ | 消息正文内容 |
| `role` | TEXT | ✅ | 消息角色：`user` 或 `assistant`，默认 `user` |
| `timestamp` | DATETIME | 自动 | 服务器生成，写入时由 SQLite 自动填充 |
| `message_type` | TEXT | ❌ | 消息类型，默认 `text`。可选值：`image`、`file`、`voice` 等 |
| `created_at` | DATETIME | 自动 | 记录创建时间，服务器生成 |

---

## 自动迁移

服务启动时会自动执行以下迁移（兼容旧数据库）：

```sql
-- 添加 role 列 (如果不存在)
ALTER TABLE chat_messages ADD COLUMN role TEXT DEFAULT 'user';

-- 添加 wecom_msg_id 列 (如果不存在)
ALTER TABLE chat_messages ADD COLUMN wecom_msg_id TEXT;
```

---

## 查询示例

### 获取最近 N 条消息
```sql
SELECT sender_name, content, role, timestamp 
FROM chat_messages 
WHERE chat_id = ? 
ORDER BY timestamp DESC 
LIMIT ?;
```

### 获取某日所有消息
```sql
SELECT sender_name, content, role, timestamp, message_type
FROM chat_messages
WHERE chat_id = ? AND DATE(timestamp) = ?
ORDER BY timestamp ASC;
```

### 按角色统计消息
```sql
SELECT role, COUNT(*) as count
FROM chat_messages
WHERE chat_id = ?
GROUP BY role;
```

### 检查消息是否已存在（去重）
```sql
SELECT id FROM chat_messages WHERE wecom_msg_id = ?;
```

---

## 运维操作

### 查看数据库
```bash
sqlite3 /opt/crewai/chat_storage.db

# 查看表结构
.schema chat_messages

# 查看最近10条消息
SELECT id, sender_name, role, substr(content, 1, 30) as content_preview 
FROM chat_messages ORDER BY id DESC LIMIT 10;

# 统计消息数量
SELECT role, COUNT(*) FROM chat_messages GROUP BY role;
```

### 备份
```bash
# 在线备份
sqlite3 chat_storage.db ".backup 'chat_storage.db.bak'"
```
