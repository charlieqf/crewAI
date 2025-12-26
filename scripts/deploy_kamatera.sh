#!/bin/bash
# =============================================================================
# WeCom Callback Server - Kamatera 部署脚本
# =============================================================================
# 
# 用法:
#   scp scripts/deploy_kamatera.sh root@104.238.213.119:/tmp/
#   ssh root@104.238.213.119 "bash /tmp/deploy_kamatera.sh"
#
# 环境变量 (必须在运行前设置):
#   WECOM_TOKEN, WECOM_ENCODING_AES_KEY, WECOM_CORP_ID
#   GEMINI_API_KEY (或其他 LLM API key)
#   WECOM_WEBHOOK_URL_GPT (或 GEMINI/GROK)
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
DATA_DIR="/var/lib/wecom-callback"
LOG_DIR="/var/log/wecom-callback"

mkdir -p "$APP_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$LOG_DIR"

# -----------------------------------------------------------------------------
# 3. 克隆/更新代码
# -----------------------------------------------------------------------------
echo ""
echo ">>> 3. 获取代码..."

DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
REPO_URL="${REPO_URL:-https://github.com/your-org/crewAI.git}"

if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$DEPLOY_BRANCH"
else
    git clone --depth 1 -b "$DEPLOY_BRANCH" "$REPO_URL" "$APP_DIR"
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
# WeCom 配置 (必填)
WECOM_TOKEN=your_token_here
WECOM_ENCODING_AES_KEY=your_aes_key_here
WECOM_CORP_ID=your_corp_id_here

# LLM API Keys (至少配置一个)
GEMINI_API_KEY=
OPENAI_API_KEY=
GROK_API_KEY=

# Webhook URLs
WECOM_WEBHOOK_URL_GPT=
WECOM_WEBHOOK_URL_GEMINI=
WECOM_WEBHOOK_URL_GROK=

# 数据存储
CHAT_DB_PATH=/var/lib/wecom-callback/chat_history.db

# 日志
LOG_DIR=/var/log/wecom-callback
LOG_LEVEL=INFO
EOF
    echo "!!! 请编辑 $ENV_FILE 填写配置 !!!"
fi

# -----------------------------------------------------------------------------
# 6. 创建 systemd 服务
# -----------------------------------------------------------------------------
echo ""
echo ">>> 6. 配置 systemd 服务..."

cat > /etc/systemd/system/wecom-callback.service << EOF
[Unit]
Description=WeCom Callback Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

# 日志
StandardOutput=append:$LOG_DIR/wecom_callback.log
StandardError=append:$LOG_DIR/wecom_callback_error.log

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
