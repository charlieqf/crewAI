# 企业微信回调服务配置指南

本文档记录如何配置企业微信应用的回调 URL，使 AI Agent 能够接收群聊消息。

---

## 1. 配置信息说明

> ⚠️ **安全提示**：实际凭据存储在 `.env` 文件中（已被 .gitignore 保护）。

| 配置项 | 环境变量名 | 说明 |
| :--- | :--- | :--- |
| **CorpID** | `WECOM_CORP_ID` | 企业 ID |
| **AgentId** | `WECOM_AGENT_ID` | 应用 ID |
| **Secret** | `WECOM_SECRET` | 应用密钥 |
| **Token** | `WECOM_TOKEN` | 回调 Token |
| **EncodingAESKey** | `WECOM_ENCODING_AES_KEY` | 消息加解密密钥 |

配置方法：复制 `.env.example` 为 `.env`，然后填入实际值。

---

## 2. 待完成事项：配置回调 URL

### 2.1 问题说明
企业微信后台需要一个 **公网可访问的 URL** 来：
1. 验证您的服务器（GET 请求）
2. 推送消息事件（POST 请求）

当前状态：
- ✅ 代码已实现：`src/crewai_enterprise/server/wecom_callback.py`
- ❌ 需要部署到公网服务器

### 2.2 配置入口
企业微信管理后台 → 应用管理 → **crewAIAgent** → 开发者接口 → **接收消息服务器配置**

### 2.3 需要填写的字段
- **URL**: `https://your-server.com/wecom/callback`（需替换为实际地址）
- **Token**: 已填 ✅
- **EncodingAESKey**: 已填 ✅

---

## 3. 部署方案

### 方案 A：腾讯云部署（生产环境推荐）

**步骤 1**：准备腾讯云 CVM
- 规格：2 核 4G 以上
- 系统：Ubuntu 22.04 或 Rocky Linux 9
- 开放端口：80, 443, 8000

**步骤 2**：部署服务
```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆代码
git clone https://github.com/charlieqf/crewAI.git
cd crewAI

# 安装依赖
uv sync
uv pip install pycryptodome fastapi uvicorn

# 配置环境变量
cp .env.example .env
nano .env  # 填入实际凭据

# 启动服务
uv run uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
```

**步骤 3**：配置域名与 HTTPS（企业微信要求 HTTPS）
- 使用 Nginx 反向代理
- 使用 Let's Encrypt 免费证书

**步骤 4**：在企业微信后台填入
```
URL: https://your-domain.com/wecom/callback
```

---

### 方案 B：本地 ngrok 测试

**步骤 1**：本地启动服务
```powershell
cd c:\work\code\crewAI
$env:PYTHONPATH="."; uv run uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
```

**步骤 2**：安装并启动 ngrok
```powershell
# 下载 ngrok: https://ngrok.com/download
ngrok http 8000
```

**步骤 3**：复制 ngrok 提供的 HTTPS 地址
```
示例: https://xxxx-xxx-xxx.ngrok-free.app
```

**步骤 4**：在企业微信后台填入
```
URL: https://xxxx-xxx-xxx.ngrok-free.app/wecom/callback
```

> ⚠️ 注意：ngrok 免费版每次重启地址会变化，仅适合测试

---

## 4. 验证流程

配置完成后，企业微信会发送 GET 请求验证：

```
GET /wecom/callback?msg_signature=xxx&timestamp=xxx&nonce=xxx&echostr=xxx
```

我们的服务需要：
1. 验证签名
2. 解密 echostr
3. 返回解密后的明文

这已在 `wecom_callback.py` 的 `verify_url` 函数中实现。

---

## 6. 架构设计原则：模块化独立部署

### 核心原则
各模块通过 **HTTP API 通信**，可独立部署在 **任意位置**。

```
┌─────────────────┐    HTTP API    ┌─────────────────┐
│ WeCom Callback  │ ◄────────────► │ GitLab Agent    │
│ (需公网 IP)     │                │ (需访问内网)     │
└─────────────────┘                └─────────────────┘
        │                                   │
        ▼                                   ▼
   企业微信服务器                       内网 GitLab
```

### 模块职责

| 模块 | 职责 | 部署要求 |
| :--- | :--- | :--- |
| **WeCom Callback** | 接收/发送企业微信消息 | 需要公网可访问 |
| **结果接收 API** | 接收审计结果并转发 | 与 WeCom Callback 同机 |
| **GitLabTool** | 调用 GitLab API | 需能访问内网 GitLab |
| **审计 Agent** | Code Review 逻辑 | 与 GitLabTool 同机 |

### 部署灵活性

✅ **可以全部部署在一台机器**（如该机器既有公网 IP 又能 VPN 到内网）

✅ **可以分开部署**（WeCom 模块在云端，GitLab 模块在内网/VPN 机器）

✅ **未来可迁移任一模块**（因为通过 HTTP API 解耦）

### 当前可选部署位置

| 位置 | 公网 IP | 内网访问 | 适合模块 |
| :--- | :---: | :---: | :--- |
| Kamatera VM (美国) | ✅ | 需测试 VPN | WeCom 模块 |
| Windows PC (VPN) | 需 ngrok | ✅ | GitLab 模块 |
| 单机部署 | 需满足两条件 | 需满足两条件 | 全部 |

---
| `src/crewai_enterprise/utils/wecom_crypto.py` | AES 解密工具 |
| `src/crewai_enterprise/utils/wecom_message.py` | 消息解析 |
| `.env` | 环境变量配置（敏感信息） |
| `.env.example` | 配置模板 |
