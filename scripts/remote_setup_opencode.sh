#!/bin/bash
set -e

echo ">>> Installing Bun..."
if ! command -v bun &> /dev/null; then
    curl -fsSL https://bun.sh/install | bash
    # Export path for current session
    export PATH="/root/.bun/bin:$PATH"
    # Also add to .bashrc for future sessions
    if ! grep -q ".bun/bin" /root/.bashrc; then
        echo 'export PATH="/root/.bun/bin:$PATH"' >> /root/.bashrc
    fi
else
    echo "Bun already installed: $(bun --version)"
fi

echo ">>> Installing OpenCode Server globally..."
if ! npm list -g @opencode-ai/server &> /dev/null; then
    npm install -g @opencode-ai/server
else
    echo "OpenCode Server already installed."
fi

# Ensure opencode is in PATH or find it
OPENCODE_BIN=$(which opencode || echo "/usr/local/bin/opencode")
echo "OpenCode version: $($OPENCODE_BIN --version || echo 'unknown')"

echo ">>> Preparing OMO directory..."
mkdir -p /opt/oh-my-opencode
if [ -d "/opt/oh-my-opencode/.git" ]; then
    echo "OMO directory exists, updating..."
    cd /opt/oh-my-opencode
    git fetch origin
    git reset --hard origin/main
else
    echo "Cloning OMO..."
    git clone https://github.com/code-yeongyu/oh-my-opencode.git /opt/oh-my-opencode
    cd /opt/oh-my-opencode
fi

echo ">>> Installing OMO dependencies with Bun..."
export PATH="/root/.bun/bin:$PATH"
bun install

echo ">>> Setup Complete!"
