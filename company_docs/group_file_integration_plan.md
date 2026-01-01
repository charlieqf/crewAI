# 群聊文件集成方案

## 方案概述

通过添加**群机器人**作为文件收集器，配合现有的**智能机器人**，实现群聊中文件的自动收集和引用功能。

**架构设计：**
```
群聊消息流程：
┌─────────────┐
│ 用户发送文件 │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  群机器人接收    │
│  1. 下载文件    │
│  2. 上传七牛云  │
│  3. 保存到DB   │
└──────┬──────────┘
       │
       │ (msg_id, filename, cloud_url)
       │
       ▼
┌─────────────────────────┐
│      SQLite 数据库      │
│  chat_files 表          │
└──────┬──────────────────┘
       │
       │ 用户 quote 文件 + @智能机器人
       │
       ▼
┌─────────────────────────┐
│   智能机器人接收         │
│   1. 获取 quoted_msg_id │
│   2. 从 DB 查找文件     │
│   3. 下载并分析         │
└─────────────────────────┘
```

---

## 用户需要完成的任务

### 任务 1：创建群机器人

#### 步骤：

1. **登录企业微信管理后台**
   - 网址：https://work.weixin.qq.com/
   - 使用管理员账号登录

2. **创建群机器人应用**
   - 导航：**应用管理** → **自建** → **创建应用**
   - 应用名称：`文件助手` 或 `File Collector`
   - 应用 Logo：选择一个合适的图标
   - 可见范围：选择需要使用的部门/成员

3. **获取应用凭证**
   - 创建完成后进入应用详情页
   - 记录以下信息：
     - **AgentId**（应用 ID）
     - **Secret**（应用密钥）
   - 这些信息稍后会用于配置服务器

4. **配置接收消息**
   - 在应用详情页找到"接收消息"或"消息接收配置"
   - 设置**URL**（回调地址）：`http://113.125.202.173/group-bot/callback`
   - 设置 **Token**：随机生成一个字符串（例如：`GroupBot2024`）
   - 设置 **EncodingAESKey**：点击"随机生成"按钮
   - **先不要点击保存**，等服务器代码部署后再保存验证

5. **添加到群聊**
   - 进入需要使用的企业微信群聊
   - 点击群聊设置 → 群机器人 → 添加机器人
   - 选择刚创建的"文件助手"应用

---

### 任务 2：提供配置信息

将以下信息提供给开发者（我）：

```bash
# 群机器人配置
GROUPBOT_AGENT_ID=<应用 ID>
GROUPBOT_SECRET=<应用密钥>
GROUPBOT_TOKEN=<上面设置的 Token>
GROUPBOT_ENCODING_AES_KEY=<上面生成的 AESKey>
```

---

## 开发工作（由我完成）

### 阶段 1：验证 msg_id 一致性

**目的：** 确认群机器人收到的 `msg_id` 与智能机器人 quote 时的 `quoted_msg_id` 是否一致。

**工作内容：**
1. 创建一个测试端点接收群机器人消息
2. 记录文件消息的 `msg_id`
3. 对比智能机器人 quote 时的 `quoted_msg_id`
4. 确认关联方式

**验证方法：**
- 在群聊发送一个测试文件
- Quote 该文件并 @智能机器人
- 检查日志确认 ID 匹配

---

### 阶段 2：实现群机器人文件收集器

**代码模块：**

1. **新增路由**：`/group-bot/callback`
   - 处理 URL 验证
   - 接收文件消息
   - 解密和验证签名

2. **文件处理逻辑**：
   ```python
   async def handle_group_file(file_msg):
       # 1. 下载文件
       file_data = download_wecom_file(file_msg['file_url'])
       
       # 2. 上传七牛云
       cloud_result = storage.upload_file(file_data, filename)
       
       # 3. 保存到数据库
       context_manager.save_file(
           chat_id=file_msg['chat_id'],
           sender_id=file_msg['sender_id'],
           wecom_msg_id=file_msg['msg_id'],  # 关键：记录 msg_id
           filename=filename,
           file_uri=cloud_result.url
       )
   ```

3. **数据库扩展**（如果需要）：
   - 确保 `chat_files` 表支持 `wecom_msg_id` 索引
   - 可能需要添加 `group_chat` 标记字段

---

### 阶段 3：智能机器人集成

**无需修改**（如果 msg_id 一致）：
- 现有的 quote 查找逻辑已经通过 `quoted_msg_id` 查找文件
- 只要群机器人正确保存了 `wecom_msg_id`，智能机器人就能找到

**可能需要的优化：**
- 添加群聊文件的特殊标记
- 优化跨 chat_id 的文件查找逻辑

---

## 部署流程

### 步骤 1：配置服务器环境变量

```bash
ssh -i ~/.ssh/kamatera root@104.238.213.119

# 编辑环境变量文件
nano /etc/wecom-callback/env

# 添加以下配置
GROUPBOT_AGENT_ID=你的应用ID
GROUPBOT_SECRET=你的应用密钥
GROUPBOT_TOKEN=你的Token
GROUPBOT_ENCODING_AES_KEY=你的AESKey

# 保存并退出
```

### 步骤 2：部署代码

```bash
cd /opt/wecom-callback
git fetch origin
git reset --hard origin/feat-wecom
systemctl restart wecom-callback
```

### 步骤 3：验证回调 URL

1. 回到企业微信管理后台
2. 点击"保存"按钮验证回调 URL
3. 如果验证成功，显示"配置成功"

---

## 验证测试

### 测试场景 1：文件自动收集

1. 在群聊中发送一个 PDF 文件（不 @ 任何人）
2. 检查服务器日志，确认群机器人收到并处理了文件
3. 检查七牛云，确认文件已上传
4. 检查数据库，确认文件记录已保存

**预期日志：**
```
[GROUPBOT] Received file message: test.pdf
[GROUPBOT] Downloaded file: 1024 bytes
[GROUPBOT] Uploaded to Qiniu: http://t83xy5wfa.sabkt.gdipper.com/wecom/...
[GROUPBOT] Saved to DB: msg_id=abc123, filename=test.pdf
```

---

### 测试场景 2：智能机器人引用

1. Quote 刚才发送的 PDF 文件
2. 在同一条消息中 @gemini 并提问
3. 检查 Gemini 是否成功识别并分析了 PDF

**预期行为：**
```
用户：[Quote PDF] @gemini 这个文件讲了什么？
Gemini：根据这份PDF文件，主要内容是...
```

**预期日志：**
```
[AIBOT_CTX] Found quoted file by MsgId: test.pdf
[AIBOT_LLM_REQ] file_ctx=True
```

---

## 风险和注意事项

### 风险 1：msg_id 不一致

**问题：** 如果群机器人的 `msg_id` 与智能机器人的 `quoted_msg_id` 不同，引用功能将失败。

**应对方案：**
- 阶段 1 的验证测试会发现这个问题
- 如果不一致，需要使用其他关联方式：
  - 时间戳 + 发送人 + 文件名组合
  - 文件 hash 值
  - 或者通过企业微信 API 查询消息详情

---

### 风险 2：群机器人权限不足

**问题：** 群机器人可能无法下载某些类型的文件。

**应对方案：**
- 测试各种文件类型（PDF, 图片, Office 文档）
- 如果权限不足，考虑使用会话存档 API

---

### 风险 3：性能影响

**问题：** 群聊中大量文件可能导致七牛云存储成本增加。

**应对方案：**
- 设置文件大小限制（例如最大 50MB）
- 设置自动清理策略（例如 30 天后删除）
- 只处理特定类型的文件（PDF, 图片）

---

## 时间估算

| 阶段 | 工作内容 | 预计时间 |
|------|---------|---------|
| 用户任务 | 创建群机器人、提供配置 | 20 分钟 |
| 阶段 1 | msg_id 验证测试 | 1 小时 |
| 阶段 2 | 群机器人开发 | 3 小时 |
| 阶段 3 | 集成和优化 | 2 小时 |
| 测试验证 | 完整功能测试 | 1 小时 |
| **总计** | | **约 7 小时开发 + 20 分钟配置** |

---

## 后续优化

完成基础功能后，可以考虑以下优化：

1. **智能文件识别**
   - 只保存特定类型的文件（PDF, Office, 图片）
   - 忽略表情包、截图等临时文件

2. **用户通知**
   - 群机器人在成功保存文件后，发送一条提示消息
   - 例如："✅ 已保存文件：test.pdf（可 @gemini 引用）"

3. **文件管理命令**
   - `@文件助手 列出文件` - 显示本群所有已保存的文件
   - `@文件助手 清理` - 清理旧文件

4. **跨群共享**
   - 允许用户在不同群聊中引用同一个文件
   - 基于用户 ID 建立全局文件索引

---

## 下一步行动

**立即开始：**
1. ✅ **用户**：创建群机器人，获取配置信息
2. ⏳ **开发者**：收到配置后，开始阶段 1 验证测试

**等待确认后：**
3. ⏳ 如果 msg_id 一致，继续阶段 2 和 3
4. ⏳ 如果 msg_id 不一致，调整关联策略

---

## 联系和支持

如果在配置过程中遇到任何问题，请提供：
- 企业微信管理后台的截图
- 群机器人的配置信息（隐藏敏感信息）
- 任何错误提示

我会及时协助解决。
