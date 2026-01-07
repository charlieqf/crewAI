#!/bin/bash
# =============================================================================
# WeCom Callback Server - Kamatera 部署脚本
# =============================================================================
# 
# 用法:
#   scp scripts/deploy_kamatera.sh root@104.238.213.119:/tmp/
#   ssh root@104.238.213.119 "bash /tmp/deploy_kamatera.sh"
#
# 环境变量 (部署后在 /etc/wecom-callback/env 中配置):
#   WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID
#   GEMINI_API_KEY, OPENAI_API_KEY, GROK_API_KEY
#   WEBHOOK_GPT, WEBHOOK_GEMINI, WEBHOOK_GROK
#
# =============================================================================

set -e

echo "=== WeCom Callback Server 部署脚本 ==="
echo "开始时间: $(date)"

# -----------------------------------------------------------------------------
# 1. 系统准备
# -----------------------------------------------------------------------------
echo ""
echo ">>> 1. 安装系统依赖..."

apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git sqlite3

# -----------------------------------------------------------------------------
# 2. 创建应用目录
# -----------------------------------------------------------------------------
echo ""
echo ">>> 2. 创建应用目录..."

APP_DIR="/opt/wecom-callback"
DATA_DIR="/var/lib/wecom-callback"  # Used by CHAT_DB_PATH in env file
LOG_DIR="/var/log/wecom-callback"   # Only used in standalone mode; systemd uses journal

mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$LOG_DIR"  # Created for standalone/fallback use

# -----------------------------------------------------------------------------
# 3. 克隆/更新代码
# -----------------------------------------------------------------------------
echo ""
echo ">>> 3. 获取代码..."

DEPLOY_BRANCH="${DEPLOY_BRANCH:-feat-wecom}"
REPO_URL="${REPO_URL:-https://github.com/charlieqf/crewAI.git}"

if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    # Safer update: stash local changes with timestamp
    if ! git diff --quiet || ! git diff --cached --quiet; then
        STASH_MSG="deploy-$(date +%Y%m%d-%H%M%S)"
        git stash push -u -m "$STASH_MSG"
        echo "Note: Local changes stashed as '$STASH_MSG'. Use 'git stash list' to view."
    fi
    git fetch origin
    # Use -B to create/reset branch to track remote; fallback to main if branch doesn't exist
    if git rev-parse --verify "origin/$DEPLOY_BRANCH" >/dev/null 2>&1; then
        git checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
    else
        echo "WARNING: Branch '$DEPLOY_BRANCH' not found on remote, falling back to 'main'"
        DEPLOY_BRANCH="main"
        git checkout -B "$DEPLOY_BRANCH" "origin/$DEPLOY_BRANCH"
    fi
else
    git clone -b "$DEPLOY_BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# -----------------------------------------------------------------------------
# 4. Python 虚拟环境
# -----------------------------------------------------------------------------
echo ""
echo ">>> 4. 设置 Python 虚拟环境..."

python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

pip install --upgrade pip
pip install -r requirements-server.txt

# -----------------------------------------------------------------------------
# 5. 创建环境配置文件
# -----------------------------------------------------------------------------
echo ""
echo ">>> 5. 创建环境配置..."

ENV_FILE="/etc/wecom-callback/env"
mkdir -p "$(dirname $ENV_FILE)"

if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
# WeCom 配置 (自建应用 - 如不使用可忽略)
WECOM_TOKEN=your_token_here
WECOM_ENCODING_AES_KEY=your_aes_key_here
WECOM_CORP_ID=your_corp_id_here

# =============================================================================
# AI Bot 智能机器人配置 (每个机器人独立的 Token 和 EncodingAESKey)
# =============================================================================
# Gemini Bot
GEMINI_BOT_TOKEN=
GEMINI_BOT_ENCODING_AES_KEY=

# ChatGPT Bot
CHATGPT_BOT_TOKEN=
CHATGPT_BOT_ENCODING_AES_KEY=

# Grok Bot
GROK_BOT_TOKEN=
GROK_BOT_ENCODING_AES_KEY=

# =============================================================================
# LLM API Keys (至少配置一个)
# =============================================================================
GEMINI_API_KEY=
OPENAI_API_KEY=
XAI_API_KEY=

# Webhook URLs (自建应用使用, 智能机器人不需要)
WEBHOOK_GPT=
WEBHOOK_GEMINI=
WEBHOOK_GROK=

# 数据存储
CHAT_DB_PATH=/var/lib/wecom-callback/chat_storage.db
ARCHIVE_DB_PATH=/var/lib/wecom-callback/chat_history.db

# 日志
LOG_DIR=/var/log/wecom-callback
LOG_LEVEL=INFO
EOF
    echo "!!! 请编辑 $ENV_FILE 填写配置 !!!"
fi

# -----------------------------------------------------------------------------
# 6. 配置系统环境与 systemd 服务
# -----------------------------------------------------------------------------
echo ""
echo ">>> 6. 配置 systemd 服务与 DNS..."

# 确保内部 GitLab 解析
if ! grep -q "gitlab.goldenstand.com" /etc/hosts; then
    echo "10.0.0.118 gitlab.goldenstand.com" >> /etc/hosts
    echo "Added gitlab.goldenstand.com to /etc/hosts"
fi

cat > /etc/systemd/system/wecom-callback.service << EOF
[Unit]
Description=WeCom Callback Server with VPN Support
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE

# 启动前确保 VPN 已连接
ExecStartPre=-/root/setup_vpn_linux.sh connect

ExecStart=$APP_DIR/venv/bin/python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

# 日志 - 使用 journal 而不是文件追加，避免重复
StandardOutput=journal
StandardError=journal
SyslogIdentifier=wecom-callback

[Install]
WantedBy=multi-user.target
EOF

# -----------------------------------------------------------------------------
# 7. 启用并启动服务
# -----------------------------------------------------------------------------
echo ""
echo ">>> 7. 启动服务..."

systemctl daemon-reload
systemctl enable wecom-callback
systemctl restart wecom-callback

# -----------------------------------------------------------------------------
# 8. 验证
# -----------------------------------------------------------------------------
echo ""
echo ">>> 8. 验证部署..."

sleep 3

if systemctl is-active --quiet wecom-callback; then
    echo "✅ 服务运行中"
else
    echo "❌ 服务启动失败"
    journalctl -u wecom-callback -n 20 --no-pager
    exit 1
fi

# 健康检查
if curl -s http://localhost:8000/health | grep -q "healthy"; then
    echo "✅ 健康检查通过"
else
    echo "❌ 健康检查失败"
fi

# -----------------------------------------------------------------------------
# 完成
# -----------------------------------------------------------------------------
echo ""
echo "=== 部署完成 ==="
echo ""
echo "下一步:"
echo "  1. 编辑 $ENV_FILE 填写配置"
echo "  2. systemctl restart wecom-callback"
echo "  3. 配置 WeCom 回调 URL: http://YOUR_IP:8000/wecom/callback"
echo ""
echo "常用命令:"
echo "  systemctl status wecom-callback    # 查看状态"
echo "  journalctl -u wecom-callback -f    # 查看日志"
echo "  systemctl restart wecom-callback   # 重启服务"
