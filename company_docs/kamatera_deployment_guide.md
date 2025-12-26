# WeCom Callback 部署指南

> **目标**: Kamatera Ubuntu 22.04 VM (`$KAMATERA_IP`)  
> **Python**: 3.10.12

## 快速部署 (一键脚本)

```bash
# 下载并执行部署脚本
curl -sSL https://raw.githubusercontent.com/charlieqf/crewAI/main/scripts/deploy.sh | bash
```

或手动按以下步骤操作：

---

## 步骤 1: 安装系统依赖

```bash
# 更新系统
apt update && apt upgrade -y

# 安装必要工具
apt install -y git python3-pip python3-venv curl

# 验证 Python 版本 (需要 3.10+)
python3 --version
```

## 步骤 2: 克隆代码

```bash
# 创建项目目录
mkdir -p /opt/crewai
cd /opt/crewai

# 从 GitHub 克隆代码
git clone https://github.com/charlieqf/crewAI.git .

# 或者从私有仓库克隆 (需要配置 SSH key)
# git clone git@github.com:your-username/crewai.git .
```

> **提示**: 如果代码在私有仓库，需要先在 VM 上配置 SSH key 或使用 Personal Access Token

## 步骤 3: 创建 Python 虚拟环境

```bash
cd /opt/crewai

# 创建虚拟环境
python3 -m venv .venv

# 激活虚拟环境
source .venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装项目依赖
pip install fastapi uvicorn[standard] requests pydantic pycryptodome python-dotenv defusedxml

# 可选: 安装 CrewAI (如需完整功能)
# pip install crewai
```

## 步骤 4: 配置环境变量

创建 `.env` 文件：

```bash
cat > /opt/crewai/.env << 'EOF'
# ===========================================
# WeCom Enterprise App Configuration
# ===========================================
WECOM_CORP_ID=your_corp_id
WECOM_AGENT_ID=your_agent_id
WECOM_SECRET=your_app_secret
WECOM_TOKEN=your_callback_token
WECOM_ENCODING_AES_KEY=your_encoding_aes_key

# ===========================================
# LLM API Keys
# ===========================================
OPENAI_API_KEY=sk-your-openai-key
GEMINI_API_KEY=your-gemini-key
XAI_API_KEY=your-grok-key

# ===========================================
# Bot Webhook URLs (从企微群设置获取)
# ===========================================
WEBHOOK_GPT=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GEMINI=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GROK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# ===========================================
# Storage Configuration
# ===========================================
CHAT_DB_PATH=chat_storage.db

# ===========================================
# GitLab (可选, 通过 SSH 隧道访问)
# ===========================================
GITLAB_URL=http://localhost:8080
GITLAB_PRIVATE_TOKEN=your_gitlab_token
EOF

# 设置文件权限 (保护敏感信息)
chmod 600 /opt/crewai/.env
```

## 步骤 5: 测试启动

```bash
cd /opt/crewai
source .venv/bin/activate
export PYTHONPATH=/opt/crewai

# 启动服务器
python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
```

验证服务运行：
```bash
# 健康检查
curl http://localhost:8000/health
# 预期返回: {"status":"healthy","service":"wecom-callback"}
```

> **注意**: `/wecom/callback` 端点需要企微签名参数 (msg_signature, timestamp, nonce)，直接访问会返回 422 错误，这是正常的。

## 步骤 6: 配置 systemd 服务

```bash
cat > /etc/systemd/system/wecom-callback.service << 'EOF'
[Unit]
Description=WeCom Callback Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/crewai
Environment="PYTHONPATH=/opt/crewai"
EnvironmentFile=/opt/crewai/.env
ExecStart=/opt/crewai/.venv/bin/python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

# 日志输出
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 重新加载 systemd 配置
systemctl daemon-reload

# 启用开机自启
systemctl enable wecom-callback

# 启动服务
systemctl start wecom-callback

# 查看状态
systemctl status wecom-callback
```

查看日志：
```bash
# 实时查看日志
journalctl -u wecom-callback -f

# 查看最近 100 行
journalctl -u wecom-callback -n 100
```

## 步骤 7: 配置防火墙

```bash
# 检查 ufw 状态
ufw status

# 开放 8000 端口
ufw allow 8000/tcp

# 如果 ufw 未启用，先启用
# ufw enable
```

## 步骤 8: 配置企微后台

1. 登录 [企业微信管理后台](https://work.weixin.qq.com/wework_admin/frame)
2. 进入「应用管理」→ 选择您的应用
3. 找到「接收消息」→「设置API接收」
4. 填入回调 URL：

```
http://$KAMATERA_IP:8000/wecom/callback
```

> **注意**: 机器人类型通过消息内容中的 @提及 自动检测，无需在URL中指定

5. Token 和 EncodingAESKey 需与 `.env` 中的配置一致

---

## 更新代码

当代码有更新时：

```bash
cd /opt/crewai
git pull origin main

# 如有新依赖, 重新安装
source .venv/bin/activate
pip install -r requirements.txt

# 重启服务
systemctl restart wecom-callback
```

---

## 故障排除

### 服务无法启动
```bash
# 查看详细日志
journalctl -u wecom-callback -e

# 检查 Python 路径
/opt/crewai/.venv/bin/python -c "import sys; print(sys.path)"
```

### 端口被占用
```bash
# 查看 8000 端口占用
lsof -i :8000
netstat -tlnp | grep 8000
```

### 回调验证失败
1. 检查 Token 和 EncodingAESKey 是否与企微后台一致
2. 确认服务正在运行：`systemctl status wecom-callback`
3. 检查防火墙：`ufw status`

---

## 验证清单

- [ ] `python3 --version` 显示 3.10+
- [ ] 代码已克隆到 `/opt/crewai`
- [ ] `.env` 文件已创建并配置
- [ ] `curl http://localhost:8000/health` 返回 healthy
- [ ] `systemctl status wecom-callback` 显示 active (running)
- [ ] 防火墙已开放 8000 端口
- [ ] 企微后台已配置回调 URL 并验证通过
