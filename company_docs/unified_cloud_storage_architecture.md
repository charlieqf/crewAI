# 统一云端存储架构 (Unified Cloud Storage - UCS)

## 概述

为实现多个 AI Bot (Gemini、ChatGPT、Grok) 在企业微信群聊中的**跨模型协作**和**长期记忆**，我们设计了统一云端存储 (UCS) 架构。该架构将所有消息类型（文字、图片、文件）的内容持久化到云端存储，并通过共享数据库索引，使任何 Bot 都能访问群聊中的完整历史信息。

---

## 架构设计

### 核心原则

> [!IMPORTANT]
> **Cross-Bot Accessibility**: 所有 Bot 共享同一个 `chat_storage.db (可通过环境变量 CHAT_DB_PATH 自定义)` 和同一个云存储桶 (Bucket)。无论用户发消息给哪个 Bot，所有 Bot 都能看到完整的上下文。

### 数据流向

#### 1. 入站流程 (Inbound - 用户发送消息)

> [!NOTE]
> 以下描述为 **UCS 目标架构**。当前实现状态见各项标注。

**详细步骤：**

- **文字消息**：
  - 接收 → 存入 `chat_storage.db` 的 `content` 字段
  - `message_type = 'text'`
  - ✅ **已实现**：跨 Bot 访问

- **图片**：
  - **目标架构**：接收 → 解密 → **上传到云存储 (Qiniu/S3)** → 获取永久 URL → 存入 DB
  - **当前实现**：接收 → 解密 → 转 Base64 → **直接发送 LLM（不入库）**
  - ⚠️ **待实现**：云存储持久化 + 跨 Bot 访问
  - 💡 **说明**：图片分析完后，Base64 数据从内存丢弃，其他 Bot 无法引用

- **文件 (PDF/Excel/Word/代码等)**：
  - **目标架构**：接收 → 解密 → **上传到云存储** → 获取永久 URL → 存入 DB
  - **当前实现**：接收 → 解密 → 转 Base64 / 上传 Gemini File API → **将 URI 存入 DB**
  - ⚠️ **问题**：Base64 字符串直接入库导致 DB 膨胀；Gemini File URI 48h 后过期
  - ⚠️ **待实现**：统一云存储 + 永久 URL
  - 💡 **说明**：文件 URI 会持久化到数据库，支持同一 Bot 引用，但跨 Bot 访问受限

#### 2. 出站流程 (Outbound - Bot 生成文件)

> [!NOTE]
> 以下描述为 **UCS 目标架构**。当前尚未实现 Bot 生成文件功能。

**详细步骤（规划中）：**

- Bot 检测到需要生成文件（如用户要求生成报表、网页等）
- 生成内容 → 上传云存储 → 获取 URL
- **双重交付**：
  1. 在群里发送云端链接（永久可访问）
  2. 上传到 WeCom Media API → 发送原生文件卡片（3天有效期）

- ❌ **当前状态**：未实现

---

## 技术栈

### 云存储选型

| 方案 | 优势 | 劣势 | 推荐场景 |
|:---|:---|:---|:---|
| **七牛云 (Qiniu)** | 国内 CDN 快速；与企业微信同生态 | 海外访问较慢 | ✅ **主推** - 服务器在国内 |
| **AWS S3** | 全球通用；稳定性高 | 国内上传需代理；费用较高 | 国际化部署 |
| **本地磁盘** | 免费；无网络延迟 | Kamatera 硬盘小；无容灾 | ❌ 不推荐 |

### 存储层实现

> [!WARNING]
> **规划中的模块**：以下 `storage_manager.py` 尚未实现，当前代码库中不存在此文件。这是 UCS 架构的核心组件，计划在 Phase 1 实施（见下文实施路径）。

**计划新增**：`src/crewai_enterprise/utils/storage_manager.py`（**待开发**）

```python
class StorageProvider(ABC):
    def upload(self, data: bytes, filename: str) -> str:
        """上传文件，返回云端 URL"""
        pass

class QiniuProvider(StorageProvider):
    # 对接七牛云 SDK
    pass

class S3Provider(StorageProvider):
    # 对接 boto3
    pass
```

**环境变量配置**：

```bash
# .env
STORAGE_PROVIDER=qiniu  # 或 s3
QINIU_ACCESS_KEY=your_key
QINIU_SECRET_KEY=your_secret
QINIU_BUCKET=wecom-bot-files
```

---

## 隔离机制

### 设计原则

系统通过 `chat_id` 实现**完全隔离**，确保不同对话之间互不干扰。

### 隔离级别

#### 1. 群聊隔离 ✅

```plaintext
群1 (chat_id = "group_abc123") 的上下文
  ├─ 用户A: "分析这个文件"
  ├─ Bot Gemini: "已分析完成"
  └─ 用户B: "再深入一点"

群2 (chat_id = "group_xyz789") 的上下文
  ├─ 用户C: "生成报表"
  └─ Bot Gemini: "报表已生成"
```

**实现机制**：
- `_extract_chat_id()` 优先提取群 ID（`chat_id`, `chatid`, `roomid` 等）
- 数据库查询：`SELECT * FROM chat_messages WHERE chat_id = ?`
- **结论**：✅ 群1 和 群2 的 Bot A 上下文完全隔离

#### 2. 单聊隔离 ✅

```plaintext
用户1 (chat_id = "user_001") 与 Bot A 的对话
  ├─ 用户1: "帮我分析财务数据"
  └─ Bot A: "已分析，利润增长20%"

用户2 (chat_id = "user_002") 与 Bot A 的对话
  ├─ 用户2: "生成本月报告"
  └─ Bot A: "报告已生成"
```

**实现机制**：
- 当 `_extract_chat_id()` 未找到群 ID 时，返回 `user_id` 作为 `chat_id`
- 每个用户的 `chat_id` 唯一
- **结论**：✅ 用户1 和 用户2 与 Bot A 的单聊完全隔离

#### 3. 单聊 vs 群聊隔离 ✅

```plaintext
用户A 单聊 Bot Gemini (chat_id = "user_A")
  └─ 敏感数据讨论

群1 中的 Bot Gemini (chat_id = "group_123")
  └─ 公开讨论
```

**实现机制**：
- 单聊的 `chat_id = user_id`
- 群聊的 `chat_id = group_id`
- 两者的 `chat_id` 永远不会冲突
- **结论**：✅ 用户A 的单聊隐私不会泄露到群聊

### 隔离保证

| 场景 | 隔离状态 | 机制 |
|:---|:---:|:---|
| 群1 vs 群2 | ✅ 完全隔离 | 不同 `group_id` |
| 用户1单聊 vs 用户2单聊 | ✅ 完全隔离 | 不同 `user_id` |
| 用户A单聊 vs 群1 | ✅ 完全隔离 | `user_id` ≠ `group_id` |
| Bot A vs Bot B（同一群） | ✅ 共享上下文 | 同一 `chat_id`（设计如此） |

### 代码实现

**核心函数**：`src/crewai_enterprise/server/aibot_callback.py` (行 232-251)

```python
def _extract_chat_id(data: dict, user_id: str) -> str:
    # 优先查找群聊 ID
    for key in ["chat_id", "chatid", "ChatId", "roomid", "room_id", "groupid"]:
        if key in data and data[key]:
            return str(data[key])  # 返回群 ID
    
    # 未找到群 ID，返回用户 ID（单聊场景）
    return user_id
```

**数据库索引**：所有查询都基于 `chat_id`

```sql
-- 保存消息
INSERT INTO chat_messages (chat_id, sender_id, content, ...) VALUES (?, ?, ?, ...)

-- 获取上下文
SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 50
```

---

## 当前架构能力矩阵

### ✅ 已实现

| 功能 | 状态 | 说明 |
|:---|:---|:---|
| 文字消息跨 Bot 访问 | ✅ | 所有 Bot 共享 `chat_storage.db (可通过环境变量 CHAT_DB_PATH 自定义)` |
| 单 Bot 文件分析 | ✅ | Gemini 可分析 PDF/Excel/图片 |
| 多 Bot 独立部署 | ✅ | Gemini/ChatGPT/Grok 各有独立 Webhook |
| 消息去重 | ⚠️ 部分实现 | 当前：基于 `wecom_msg_id`（会阻止多 Bot 并发）；目标：`(wecom_msg_id, bot_type)` 组合键 |
| 流式回复 | ✅ | 支持企业微信的"思考中…"交互 |
| 完全隔离（群/单聊） | ✅ | 基于 `chat_id` 的严格隔离 |

### ⚠️ 部分实现

| 功能 | 当前状态 | UCS 架构完成后 |
|:---|:---|:---|
| 文件跨 Bot 访问 | ❌ 仅存临时 URI | ✅ 云端 URL，任意 Bot 可分析 |
| 图片跨 Bot 访问 | ❌ 不持久化 | ✅ 云端 URL，支持跨 Bot Vision |
| Bot 生成文件 | ❌ 无此功能 | ✅ 生成 HTML/Excel 并发送 |

### ❌ 尚未实现

| 功能 | 当前状态 | 技术难度 | 备注 |
|:---|:---|:---|:---|
| Bot 之间互相对话 | ❌ | 🟡 中 | 需要"Bot 自主发起消息"逻辑 |
| Bot 主动 @ 其他 Bot | ❌ | 🔴 高 | WeCom API 限制 |
| 多 Bot 并发回复同一条消息 | ❌ | 🟢 低 | 需禁用去重或改为多流并发 |
| Bot 感知其他 Bot 的回复 | ❌ | 🟡 中 | 需区分消息来源（人/Bot） |
| 长期记忆（超过 50 条） | ⚠️ | 🟢 低 | 当前限制 50 条，可扩展 |

---

## 离"理想协作"的差距分析

### 🎯 目标愿景：多 Bot 像人类一样自由讨论

**理想场景举例**：
> 你在群里发了一张建筑设计图，@Gemini 问"这个结构是否合理？"  
> Gemini 回复："从力学角度看没问题，但美学上可以优化。"  
> 你接着问 @ChatGPT："那你有什么建议？"  
> ChatGPT 看到图片和 Gemini 的回复，说："我建议增加一个飘窗。"  
> Gemini 自动回复："飘窗会增加成本 15%，需要权衡。"  
> （三方像人类一样自然讨论）

### 🔍 当前障碍

#### 1. **Bot 无法主动发言** (Blocker)

**问题**：企业微信 Bot API 只允许"被动回复"用户消息，不能主动发起对话。

**影响**：Gemini 无法在看到 ChatGPT 的回复后主动插话。

**可能解决方案**：
- 使用"应用消息推送"API（需申请企业应用权限）
- 或设计"隐形触发"机制（如定时轮询群聊，检测其他 Bot 回复）

#### 2. **消息来源识别不完善** (🟡 中等难度)

**问题**：当前 `chat_storage.db (可通过环境变量 CHAT_DB_PATH 自定义)` 只记录 `sender_id` 和 `role`（user/assistant），但没有区分**哪个 Bot** 发的消息。

**影响**：Bot A 无法判断某条回复是 Bot B 说的还是用户说的。

**解决方案**：
- 在 DB schema 中新增 `bot_type` 字段
- 保存消息时，标记 `bot_type = 'gemini'` 或 `'chatgpt'`
- Bot 构建上下文时，能看到"这是 Gemini 的观点"

#### 3. **并发回复机制缺失** (🟢 低难度)

**问题**：当前的去重逻辑会阻止多个 Bot 同时回复同一条消息。

**影响**：你无法同时问 Gemini 和 ChatGPT 同一个问题并对比答案。

**解决方案**：
- 改进去重逻辑：`key = (wecom_msg_id, bot_type)`
- 允许不同 Bot 对同一消息生成独立的 `stream_id`

#### 4. **@人机制未实现** (🔴 高难度)

**问题**：Bot 无法在回复中 @ 其他 Bot 或用户。

**影响**：无法实现"Gemini 建议 ChatGPT 补充信息"这类协作。

**解决方案**：
- 企业微信 Bot 的文本消息可以包含 `<@userid>` 语法
- 需实现"Bot 意图识别" → 自动生成 @ 标签

---

## 实施路径

### Phase 1: UCS 基础设施 (预计 2 周)

- [x] 方案设计与文档编写
- [ ] 实现 `StorageManager` 抽象层
- [ ] 对接七牛云 SDK
- [ ] 图片上传到云存储
- [ ] 文件上传到云存储（替换现有 Base64 方案）
- [ ] DB Schema 优化（新增 `bot_type` 字段）

### Phase 2: 协作能力增强 (预计 1 周)

- [ ] 实现消息来源识别
- [ ] 支持并发回复（多 Bot 同时响应）
- [ ] Bot 生成文件并发送
- [ ] 扩展上下文窗口（支持更长历史）

### Phase 3: 高级协作 (预计 2-3 周，需实验)

- [ ] Bot 感知其他 Bot 的回复
- [ ] Bot 主动发言机制（基于应用消息 API）
- [ ] @ 其他 Bot 的意图识别
- [ ] 多 Bot 联合推理（如 Gemini 分析图片 → ChatGPT 生成报告）

---

## 风险与限制

### 技术限制

1. **企业微信 API 约束**：
   - Bot 不能主动发起对话（除非升级为企业应用）
   - 消息推送有速率限制（20 条/分钟）

2. **云存储成本**：
   - 七牛云按流量计费，大量图片/文件会产生费用
   - 建议设置生命周期策略（如 7 天自动删除）

3. **LLM API 兼容性**：
   - ChatGPT 和 Grok 的 File API 与 Gemini 不完全一致
   - 需针对性适配（已在 `llm_router.py` 中处理）

### 隐私与安全

- 所有文件会上传到第三方云服务（七牛云/AWS）
- 建议使用**私有 Bucket** + 带签名的临时 URL
- 敏感文件可选择"仅内存处理"模式（不持久化）

---

## 总结

### 当前能做到

✅ 多个 AI Bot 在同一群聊中，**共享文字对话历史**  
✅ 你可以引用之前的文件，让不同的 Bot 分析  
✅ 每个 Bot 独立思考，给出不同视角的答案  
✅ **完全隔离**：不同群/用户的对话互不干扰

### UCS 完成后能做到

✅ **文字 + 图片 + 文件** 全部可跨 Bot 访问  
✅ Bot 可以生成 Excel/HTML 文件并分享给你  
✅ 长期记忆（云端存储，不受时间限制）  

### 仍无法做到（需 Phase 3）

❌ Bot 之间主动对话（"Gemini，你觉得呢？"）  
❌ Bot 感知其他 Bot 的观点并据此调整回复  
❌ 多 Bot 自组织协作（如自动分工：A 负责数据分析，B 负责报告）  

**最大瓶颈**：企业微信 Bot API 的"被动回复"限制。要突破这一点，需要申请**企业自建应用**权限，使用应用消息 API 主动推送。
