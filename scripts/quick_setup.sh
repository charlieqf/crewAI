#!/bin/bash
# =============================================================================
# Quick Setup Script - Run directly on Kamatera VM
# =============================================================================
# Usage: sudo ./quick_setup.sh
#        or: Copy and paste this entire script into SSH terminal as root
# =============================================================================

set -e

# Check for root
if [ "$EUID" -ne 0 ]; then
    echo "❌ 请以 root 权限运行此脚本"
    echo "   sudo ./quick_setup.sh"
    exit 1
fi

echo "🚀 Starting WeCom Callback Service Setup..."

# Configuration
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
REPO_URL="https://github.com/charlieqf/crewAI.git"

# 1. Install system dependencies
echo "📦 Installing system dependencies..."
apt update && apt install -y git python3-pip python3-venv curl

# 2. Create project directory
echo "📁 Creating project directory..."
mkdir -p /opt/crewai
cd /opt/crewai

# 3. Clone repository
echo "📥 Cloning repository..."
if [ -d ".git" ]; then
    echo "Repository exists, pulling latest..."
    git pull origin "$DEPLOY_BRANCH"
else
    git clone "$REPO_URL" .
fi

# 4. Create virtual environment
echo "🐍 Setting up Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 5. Install dependencies
echo "📦 Installing Python dependencies..."
if [ -f "requirements-server.txt" ]; then
    pip install -r requirements-server.txt
else
    pip install fastapi uvicorn[standard] requests pydantic pycryptodome python-dotenv defusedxml openai
fi

# 6. Create .env template if not exists
if [ ! -f ".env" ]; then
    echo "📝 Creating .env template..."
    cat > .env << 'EOF'
# WeCom Configuration
WECOM_CORP_ID=your_corp_id
WECOM_AGENT_ID=your_agent_id
WECOM_SECRET=your_app_secret
WECOM_TOKEN=your_callback_token
WECOM_ENCODING_AES_KEY=your_encoding_aes_key

# LLM API Keys
OPENAI_API_KEY=sk-your-openai-key
GEMINI_API_KEY=your-gemini-key
XAI_API_KEY=your-grok-key

# Bot Webhook URLs
WEBHOOK_GPT=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GEMINI=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GROK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# Storage
CHAT_DB_PATH=chat_storage.db
EOF
    chmod 600 .env
    echo "⚠️  请编辑 /opt/crewai/.env 填入真实凭证!"
fi

echo ""
echo "============================================="
echo "✅ Setup complete!"
echo "============================================="
echo ""
echo "📝 Next steps:"
echo "   1. Edit credentials: nano /opt/crewai/.env"
echo "   2. Test run:"
echo "      cd /opt/crewai"
echo "      source .venv/bin/activate"
echo "      export PYTHONPATH=/opt/crewai"
echo "      python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000"
echo ""
echo "   3. Or run full deploy script for systemd service:"
echo "      ./scripts/deploy.sh"
echo ""
