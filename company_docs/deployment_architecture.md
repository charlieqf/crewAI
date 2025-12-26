# CrewAI 部署架构文档

> 更新时间: 2025-12-26

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                 公司内网 (CentOS 7.9)                           │
│  ┌─────────────┐                  ┌────────────────────────┐   │
│  │ GitLab      │ ◄───内网 IP──────│ gitlab-tunnel.service  │   │
│  │ (内网地址)  │                  │ (autossh 自动重连)      │   │
│  └─────────────┘                  └──────────┬─────────────┘   │
└───────────────────────────────────────────────┼─────────────────┘
                                                │ SSH -R 8080
                                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Kamatera VM (公有云)                            │
│  localhost:8080 ──► 内网 GitLab                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ CrewAI 主服务                                           │   │
│  │ - WeCom Callback (接收/发送企微消息)                     │   │
│  │ - OpenHands (代码执行)                                  │   │
│  │ - LLM API (OpenAI/Claude 直接访问)                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 服务器信息

| 服务器 | 地址 | 系统 | 用途 |
| :--- | :--- | :--- | :--- |
| CentOS VM | 内网 | CentOS 7.9 / Python 3.7 | GitLab 隧道代理 |
| Kamatera VM | `$KAMATERA_IP` | Ubuntu 22.04 | CrewAI 主服务 |
| GitLab | `$GITLAB_INTERNAL_IP`:80 | - | 代码仓库 |

> **注意**: 实际 IP 地址请查阅内部配置文档或 `.env` 文件

---

## CentOS VM 配置

### 已部署服务

#### 1. gitlab-tunnel.service (SSH 反向隧道)

**服务文件路径**: `/etc/systemd/system/gitlab-tunnel.service`

```ini
[Unit]
Description=GitLab SSH Reverse Tunnel to Kamatera
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/autossh -M 0 -N -o "ServerAliveInterval=30" -o "ServerAliveCountMax=3" -o "ExitOnForwardFailure=yes" -R 8080:$GITLAB_INTERNAL_IP:80 root@$KAMATERA_IP
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**管理命令**:
```bash
# 查看状态
systemctl status gitlab-tunnel

# 重启服务
systemctl restart gitlab-tunnel

# 查看日志
journalctl -u gitlab-tunnel -f
```

### SSH 配置

- **密钥位置**: `/root/.ssh/id_rsa`
- **目标服务器**: Kamatera VM

---

## Kamatera VM 配置

### SSH 优化

已在 `/etc/ssh/sshd_config` 添加:
```
UseDNS no
```

### 端口映射

| 本地端口 | 映射目标 | 说明 |
| :--- | :--- | :--- |
| localhost:8080 | 内网 GitLab | 通过 SSH 隧道访问 |

---

## 验证方法

### 1. 检查隧道服务状态 (CentOS VM)
```bash
systemctl status gitlab-tunnel
```
预期: `Active: active (running)`

### 2. 测试 GitLab 访问 (Kamatera VM)
```bash
curl -s http://localhost:8080 | head -5
```
预期: 返回 GitLab HTML (如登录重定向)

### 3. 测试 SSH 连接延迟 (CentOS VM)
```bash
time ssh root@$KAMATERA_IP "echo 'test'"
```
预期: ~2 秒

---

## 故障排除

### 隧道断开

1. 检查 CentOS VM 网络:
   ```bash
   ping -c 3 $KAMATERA_IP
   ```

2. 重启服务:
   ```bash
   systemctl restart gitlab-tunnel
   ```

3. 查看详细日志:
   ```bash
   journalctl -u gitlab-tunnel --since "10 minutes ago"
   ```

### 连接超时

检查 Kamatera VM 防火墙:
```bash
# 在 Kamatera VM 上
ufw status
iptables -L -n
```

---

## 环境变量说明

以下环境变量需要在部署时配置:

| 变量名 | 说明 |
| :--- | :--- |
| `KAMATERA_IP` | Kamatera VM 公网 IP |
| `GITLAB_INTERNAL_IP` | 内网 GitLab 服务器 IP |

实际值请查阅内部配置文档或联系运维团队。

---

## 待部署项目

- [x] SSH 隧道服务 (gitlab-tunnel)
- [ ] CrewAI 主服务
- [ ] WeCom Callback 服务
- [ ] OpenHands 集成
- [ ] 环境变量配置 (.env)
