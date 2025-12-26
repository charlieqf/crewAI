# WeCom Callback 部署待办清单

本文档记录 WeCom Callback Server 上线前需要完成的任务。

---

## 状态总览

| 阶段 | 状态 | 说明 |
| :--- | :---: | :--- |
| 代码开发 | ✅ | 核心功能已完成 |
| 本地测试 | ⏳ | 需要完善单元测试 |
| 服务部署 | ❌ | 待部署到 Kamatera |
| 企业微信配置 | ❌ | 待配置回调 URL |
| 生产验证 | ❌ | 待测试完整链路 |

---

## 待办事项

### 1. 部署服务到 Kamatera VM

**优先级**: 🔴 高

**步骤**:

- [ ] 1.1 复制部署脚本到服务器
  ```powershell
  scp -i $env:USERPROFILE\.ssh\kamatera scripts\deploy_kamatera.sh root@104.238.213.119:/tmp/
  ```

- [ ] 1.2 SSH 登录服务器
  ```powershell
  ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119
  ```

- [ ] 1.3 运行部署脚本
  ```bash
  bash /tmp/deploy_kamatera.sh
  ```

- [ ] 1.4 编辑环境配置文件
  ```bash
  nano /etc/wecom-callback/env
  ```
  
  需要配置:
  - [ ] `WECOM_TOKEN` - 企业微信 Token
  - [ ] `WECOM_ENCODING_AES_KEY` - 企业微信 AES Key
  - [ ] `WECOM_CORP_ID` - 企业 ID
  - [ ] `GEMINI_API_KEY` - Gemini API 密钥
  - [ ] `OPENAI_API_KEY` - OpenAI API 密钥 (可选)
  - [ ] `WEBHOOK_GEMINI` - Gemini 机器人 Webhook URL
  - [ ] `WEBHOOK_GPT` - GPT 机器人 Webhook URL (可选)

- [ ] 1.5 重启服务
  ```bash
  systemctl restart wecom-callback
  ```

- [ ] 1.6 验证服务状态
  ```bash
  systemctl status wecom-callback
  curl http://localhost:8000/health
  ```

---

### 2. 配置企业微信管理后台

**优先级**: 🔴 高

**前提**: 服务已部署并运行

**步骤**:

- [ ] 2.1 登录 [企业微信管理后台](https://work.weixin.qq.com/wework_admin/frame)

- [ ] 2.2 进入应用配置
  - 路径: `应用管理` → `自建应用` → 选择或创建应用

- [ ] 2.3 配置接收消息
  - 路径: `接收消息` → `设置API接收`
  - URL: `http://104.238.213.119:8000/wecom/callback`
  - Token: 与 `/etc/wecom-callback/env` 中 `WECOM_TOKEN` 一致
  - EncodingAESKey: 与 `WECOM_ENCODING_AES_KEY` 一致

- [ ] 2.4 点击保存，企业微信会验证 URL
  - 验证成功: 保存成功
  - 验证失败: 检查 Token/AESKey 配置

- [ ] 2.5 创建群机器人 Webhook
  - 在目标群 → `群设置` → `群机器人` → `添加` → `新建`
  - 复制 Webhook URL
  - 填入 `/etc/wecom-callback/env` 的 `WEBHOOK_GEMINI` 或 `WEBHOOK_GPT`

---

### 3. 生产环境验证

**优先级**: 🔴 高

**前提**: 步骤 1、2 完成

**步骤**:

- [ ] 3.1 发送测试消息
  ```
  在群里发送: @gemini 你好
  ```

- [ ] 3.2 检查日志
  ```powershell
  python scripts\ops_logs.py tail
  ```

- [ ] 3.3 验证回复是否正常

- [ ] 3.4 测试清空命令
  ```
  在群里发送: /清空
  ```

- [ ] 3.5 测试不同机器人 (如果配置了多个)
  ```
  @gpt 你好
  @grok 你好
  ```

---

### 4. 代码质量改进

**优先级**: 🟡 中

- [ ] 4.1 修复 lint 警告
  - `defusedxml` 导入问题
  - `ET` 别名问题
  - 未使用的变量
  - 字符串编码声明

- [ ] 4.2 添加单元测试
  - `test_wecom_callback.py` - 回调处理测试
  - `test_text_handler.py` - 文本处理测试
  - `test_chat_storage.py` - 存储测试

- [ ] 4.3 添加集成测试
  - 端到端消息处理测试

---

### 5. 安全加固

**优先级**: 🟡 中

- [ ] 5.1 配置 HTTPS (可选但推荐)
  - 使用 Nginx 反向代理 + Let's Encrypt

- [ ] 5.2 配置防火墙
  ```bash
  ufw allow 8000/tcp
  ufw allow 22/tcp
  ufw enable
  ```

- [ ] 5.3 定期轮转 API Keys

---

### 6. 监控告警

**优先级**: 🟢 低

- [ ] 6.1 设置健康检查监控
  - 使用 UptimeRobot 或类似服务
  - 监控 `http://104.238.213.119:8000/health`

- [ ] 6.2 设置日志告警
  - 监控 `[FATAL]` 和 `[LLM_ERR]` 日志

- [ ] 6.3 设置磁盘空间告警
  - 日志目录和数据库大小

---

### 7. 文档完善

**优先级**: 🟢 低

- [ ] 7.1 更新 README.md

- [ ] 7.2 添加 API 文档

- [ ] 7.3 添加架构图

---

## 已完成项目

### 代码开发

- [x] WeCom 回调服务器 (`wecom_callback.py`)
- [x] 消息处理器 (`text_handler.py`, `file_handler.py`)
- [x] LLM 路由器 (`llm_router.py`)
- [x] 聊天上下文管理 (`chat_context.py`)
- [x] 聊天存储工具 (`chat_storage_tool.py`)
- [x] 消息解析与加密 (`wecom_message.py`, `wecom_crypto.py`)

### 日志与运维

- [x] 日志配置 (`logging_config.py`)
- [x] 运维脚本 (`ops_logs.py`)
- [x] 部署脚本 (`deploy_kamatera.sh`)

### 文档

- [x] 运维手册 (`operations_manual.md`)
- [x] 消息链路与故障排查 (`message_flow_and_troubleshooting.md`)
- [x] 数据库 Schema (`database_schema.md`)
- [x] 部署架构 (`deployment_architecture.md`)

### SSH 配置

- [x] 生成 SSH 密钥
- [x] 添加公钥到 Kamatera VM
- [x] 验证免密码登录

---

## 备注

### 环境变量获取方式

| 变量 | 获取方式 |
| :--- | :--- |
| `WECOM_TOKEN` | 企业微信后台 → 应用 → 接收消息设置 → 随机生成 |
| `WECOM_ENCODING_AES_KEY` | 同上 → 随机生成 |
| `WECOM_CORP_ID` | 企业微信后台 → 我的企业 → 企业ID |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/apikey) |
| `OPENAI_API_KEY` | [OpenAI Platform](https://platform.openai.com/api-keys) |
| `WEBHOOK_*` | 企业微信群 → 群机器人 → Webhook URL |

---

*文档更新时间: 2025-12-26*
