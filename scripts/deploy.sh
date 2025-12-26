#!/bin/bash
# =============================================================================
# WeCom Callback Service - Deployment Script for Ubuntu 22.04
# =============================================================================
# Usage: 
#   curl -sSL https://raw.githubusercontent.com/your-repo/crewai/main/scripts/deploy.sh | bash
#   or
#   ./scripts/deploy.sh
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_DIR="/opt/crewai"
VENV_DIR="$PROJECT_DIR/.venv"
SERVICE_NAME="wecom-callback"
SERVICE_PORT=8000

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

# =============================================================================
# Installation Steps
# =============================================================================

install_system_deps() {
    log_info "Installing system dependencies..."
    apt update
    apt install -y git python3-pip python3-venv curl
}

setup_project_dir() {
    log_info "Setting up project directory..."
    mkdir -p "$PROJECT_DIR"
    cd "$PROJECT_DIR"
}

clone_or_update_repo() {
    log_info "Cloning/updating repository..."
    
    # Use DEPLOY_BRANCH env var or default to 'main'
    local branch="${DEPLOY_BRANCH:-main}"
    
    if [ -d "$PROJECT_DIR/.git" ]; then
        log_info "Repository exists, pulling latest changes from $branch..."
        cd "$PROJECT_DIR"
        git fetch origin
        git checkout "$branch"
        git pull origin "$branch"
    else
        log_info "Cloning repository..."
        read -p "Enter Git repository URL: " GIT_REPO_URL
        git clone -b "$branch" "$GIT_REPO_URL" "$PROJECT_DIR"
    fi
}

setup_venv() {
    log_info "Setting up Python virtual environment..."
    cd "$PROJECT_DIR"
    
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
    
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    
    # Install dependencies
    pip install fastapi uvicorn[standard] requests pydantic pycryptodome python-dotenv defusedxml
    
    # Install from requirements.txt if exists
    if [ -f "$PROJECT_DIR/requirements.txt" ]; then
        pip install -r "$PROJECT_DIR/requirements.txt"
    fi
}

create_env_file() {
    log_info "Creating .env file..."
    
    if [ -f "$PROJECT_DIR/.env" ]; then
        log_warn ".env file already exists. Skipping..."
        return
    fi
    
    cat > "$PROJECT_DIR/.env" << 'EOF'
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
# Bot Webhook URLs
# ===========================================
WEBHOOK_GPT=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GEMINI=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
WEBHOOK_GROK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# ===========================================
# Storage Configuration
# ===========================================
CHAT_DB_PATH=chat_storage.db
EOF
    
    chmod 600 "$PROJECT_DIR/.env"
    log_warn "Please edit $PROJECT_DIR/.env with your actual credentials!"
}

create_systemd_service() {
    log_info "Creating systemd service..."
    
    cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=WeCom Callback Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
Environment="PYTHONPATH=$PROJECT_DIR"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$VENV_DIR/bin/python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port $SERVICE_PORT
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
}

configure_firewall() {
    log_info "Configuring firewall..."
    
    if command -v ufw &> /dev/null; then
        ufw allow $SERVICE_PORT/tcp
        log_info "UFW: Allowed port $SERVICE_PORT"
    else
        log_warn "UFW not found. Please configure firewall manually."
    fi
}

start_service() {
    log_info "Starting service..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    systemctl status "$SERVICE_NAME" --no-pager
}

verify_deployment() {
    log_info "Verifying deployment..."
    
    # Wait for service to be ready
    sleep 3
    
    # Health check
    HEALTH_RESPONSE=$(curl -s http://localhost:$SERVICE_PORT/health || echo "FAILED")
    
    if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
        log_info "✅ Health check passed!"
        echo "$HEALTH_RESPONSE"
    else
        log_error "❌ Health check failed!"
        echo "$HEALTH_RESPONSE"
        exit 1
    fi
}

print_summary() {
    echo ""
    echo "============================================="
    echo -e "${GREEN}Deployment Complete!${NC}"
    echo "============================================="
    echo ""
    echo "📁 Project directory: $PROJECT_DIR"
    echo "🔧 Service name: $SERVICE_NAME"
    echo "🌐 Service URL: http://$(hostname -I | awk '{print $1}'):$SERVICE_PORT"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Edit $PROJECT_DIR/.env with your credentials"
    echo "   2. Restart service: systemctl restart $SERVICE_NAME"
    echo "   3. Configure WeCom callback URL in admin console"
    echo ""
    echo "🔗 Callback URL:"
    echo "   http://$(hostname -I | awk '{print $1}'):$SERVICE_PORT/wecom/callback"
    echo ""
    echo "   Note: Bot type is auto-detected by @mention in message content"
    echo ""
    echo "📊 Useful commands:"
    echo "   - View logs: journalctl -u $SERVICE_NAME -f"
    echo "   - Restart:   systemctl restart $SERVICE_NAME"
    echo "   - Status:    systemctl status $SERVICE_NAME"
    echo ""
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "============================================="
    echo "WeCom Callback Service - Deployment Script"
    echo "============================================="
    echo ""
    
    check_root
    install_system_deps
    setup_project_dir
    clone_or_update_repo
    setup_venv
    create_env_file
    create_systemd_service
    configure_firewall
    start_service
    verify_deployment
    print_summary
}

main "$@"
