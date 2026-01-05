#!/bin/bash
#
# Goldenstand L2TP/IPSec VPN 连接脚本 (Linux 版)
# 使用 strongswan + xl2tpd
#
# 使用方法:
#   1. 首次运行: sudo ./setup_vpn.sh install   # 安装依赖并配置
#   2. 连接 VPN:  sudo ./setup_vpn.sh connect   # 连接并添加路由
#   3. 断开 VPN:  sudo ./setup_vpn.sh disconnect
#
# 需要设置环境变量（或修改下面的配置）:
#   VPN_USER=你的用户名
#   VPN_PASS=你的密码
#

set -e

# ==================== VPN 配置 ====================
# 从环境变量读取敏感信息 (避免在代码仓库中硬编码)
VPN_NAME="${VPN_NAME:-Goldenstand_L2TP}"
VPN_SERVER="${VPN_SERVER:?请设置 VPN_SERVER 环境变量}"
VPN_PSK="${VPN_PSK:?请设置 VPN_PSK 环境变量}"
VPN_DNS="${VPN_DNS:-}"

# 需要走 VPN 的内网路由 (可通过 VPN_ROUTES 环境变量覆盖，用逗号分隔)
if [ -n "${VPN_ROUTES:-}" ]; then
    IFS=',' read -ra INTERNAL_ROUTES <<< "$VPN_ROUTES"
else
    INTERNAL_ROUTES=(
        "10.10.10.0/24"
        "172.16.6.0/24"
        "172.16.7.0/24"
        "192.168.1.0/24"
        "10.0.0.0/24"
    )
fi

# 用户名和密码（建议通过环境变量传入，避免硬编码）
VPN_USER="${VPN_USER:-}"
VPN_PASS="${VPN_PASS:-}"

# ==================== 函数定义 ====================

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "请以 root 权限运行此脚本"
        exit 1
    fi
}

install_deps() {
    echo "=== 安装依赖 ==="
    
    if command -v apt-get &> /dev/null; then
        # Debian/Ubuntu
        apt-get update
        apt-get install -y strongswan xl2tpd ppp
    elif command -v yum &> /dev/null; then
        # CentOS/RHEL
        yum install -y epel-release
        yum install -y strongswan xl2tpd ppp
    elif command -v dnf &> /dev/null; then
        # Fedora
        dnf install -y strongswan xl2tpd ppp
    else
        echo "不支持的发行版，请手动安装 strongswan, xl2tpd, ppp"
        exit 1
    fi
}

configure_ipsec() {
    echo "=== 配置 IPSec (strongswan) ==="
    
    cat > /etc/ipsec.conf << EOF
config setup
    charondebug="ike 1, knl 1, cfg 1"
    uniqueids=no

conn ${VPN_NAME}
    keyexchange=ikev1
    authby=secret
    type=transport
    left=%defaultroute
    leftprotoport=17/1701
    right=${VPN_SERVER}
    rightprotoport=17/1701
    auto=add
EOF

    cat > /etc/ipsec.secrets << EOF
: PSK "${VPN_PSK}"
EOF
    chmod 600 /etc/ipsec.secrets
}

configure_xl2tpd() {
    echo "=== 配置 xl2tpd ==="
    
    mkdir -p /var/run/xl2tpd
    
    cat > /etc/xl2tpd/xl2tpd.conf << EOF
[lac ${VPN_NAME}]
lns = ${VPN_SERVER}
ppp debug = yes
pppoptfile = /etc/ppp/options.l2tpd.client
length bit = yes
EOF
}

configure_ppp() {
    echo "=== 配置 PPP ==="
    
    if [ -z "$VPN_USER" ] || [ -z "$VPN_PASS" ]; then
        echo "错误: 请设置 VPN_USER 和 VPN_PASS 环境变量"
        echo "例如: export VPN_USER='你的用户名'"
        echo "      export VPN_PASS='你的密码'"
        exit 1
    fi
    
    cat > /etc/ppp/options.l2tpd.client << EOF
ipcp-accept-local
ipcp-accept-remote
refuse-eap
require-chap
noccp
noauth
mtu 1280
mru 1280
noipdefault
defaultroute
usepeerdns
connect-delay 5000
persist
maxfail 0
lcp-echo-interval 20
lcp-echo-failure 3
name ${VPN_USER}
password ${VPN_PASS}
EOF
    chmod 600 /etc/ppp/options.l2tpd.client
}

install_vpn() {
    check_root
    install_deps
    configure_ipsec
    configure_xl2tpd
    configure_ppp
    
    echo ""
    echo "=== 安装完成 ==="
    echo "使用方法:"
    echo "  连接: sudo ./setup_vpn.sh connect"
    echo "  断开: sudo ./setup_vpn.sh disconnect"
}

connect_vpn() {
    check_root
    
    echo "=== 启动 IPSec ==="
    systemctl restart strongswan || ipsec restart
    sleep 2
    ipsec up ${VPN_NAME}
    
    echo "=== 启动 xl2tpd ==="
    systemctl restart xl2tpd
    sleep 2
    
    echo "=== 建立 L2TP 连接 ==="
    echo "c ${VPN_NAME}" > /var/run/xl2tpd/l2tp-control
    sleep 5
    
    # 检查 ppp 接口
    PPP_IF=$(ip link | grep -o 'ppp[0-9]*' | head -1)
    if [ -z "$PPP_IF" ]; then
        echo "错误: PPP 接口未建立，请检查日志"
        echo "查看日志: journalctl -u xl2tpd -f"
        exit 1
    fi
    
    echo "=== 添加路由 ==="
    for route in "${INTERNAL_ROUTES[@]}"; do
        echo "添加路由: $route via $PPP_IF"
        ip route add "$route" dev "$PPP_IF" 2>/dev/null || true
    done
    
    echo ""
    echo "=== VPN 已连接 ==="
    echo "PPP 接口: $PPP_IF"
    ip addr show "$PPP_IF" | grep inet
}

disconnect_vpn() {
    check_root
    
    echo "=== 断开 L2TP ==="
    echo "d ${VPN_NAME}" > /var/run/xl2tpd/l2tp-control 2>/dev/null || true
    sleep 2
    
    echo "=== 停止服务 ==="
    ipsec down ${VPN_NAME} 2>/dev/null || true
    
    echo "=== VPN 已断开 ==="
}

show_status() {
    echo "=== IPSec 状态 ==="
    ipsec statusall 2>/dev/null || echo "IPSec 未运行"
    
    echo ""
    echo "=== PPP 接口 ==="
    ip link | grep ppp || echo "无 PPP 接口"
    
    echo ""
    echo "=== 路由表 (相关网段) ==="
    ip route | grep -E '10\.|172\.|192\.168' || echo "无相关路由"
}

# ==================== 主程序 ====================

case "${1:-help}" in
    install)
        install_vpn
        ;;
    connect)
        connect_vpn
        ;;
    disconnect)
        disconnect_vpn
        ;;
    status)
        show_status
        ;;
    *)
        echo "Goldenstand L2TP VPN 管理脚本"
        echo ""
        echo "用法: $0 {install|connect|disconnect|status}"
        echo ""
        echo "  install    - 首次安装，配置 VPN"
        echo "  connect    - 连接 VPN"
        echo "  disconnect - 断开 VPN"
        echo "  status     - 查看连接状态"
        echo ""
        echo "首次使用前，请设置环境变量:"
        echo "  export VPN_SERVER='VPN服务器地址'"
        echo "  export VPN_PSK='VPN预共享密钥'"
        echo "  export VPN_USER='你的VPN用户名'"
        echo "  export VPN_PASS='你的VPN密码'"
        echo ""
        echo "可选环境变量:"
        echo "  VPN_NAME   - VPN连接名称 (默认: Goldenstand_L2TP)"
        echo "  VPN_DNS    - VPN DNS服务器"
        echo "  VPN_ROUTES - 逗号分隔的路由列表"
        ;;
esac
