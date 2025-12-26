# WeCom Callback 运维手册

本文档包含 WeCom Callback Server 的日常运维操作指南。

## 目录

1. [服务架构概览](#服务架构概览)
2. [本地环境配置](#本地环境配置)
3. [日常运维命令](#日常运维命令)
4. [VM 重启后操作](#vm-重启后操作)
5. [故障排查指南](#故障排查指南)
6. [日志管理](#日志管理)
7. [数据库维护](#数据库维护)
8. [部署与更新](#部署与更新)

---

## 服务架构概览

| 组件 | 位置 | 说明 |
| :--- | :--- | :--- |
| 应用代码 | `/opt/wecom-callback/` | Git 仓库克隆 |
| Python 虚拟环境 | `/opt/wecom-callback/venv/` | 依赖隔离 |
| 环境配置 | `/etc/wecom-callback/env` | API keys, tokens |
| SQLite 数据库 | `/var/lib/wecom-callback/chat_history.db` | 消息持久化 |
| 日志目录 | `/var/log/wecom-callback/` | 应用日志 |
| systemd 服务 | `wecom-callback.service` | 进程管理 |

---

## 本地环境配置

### Windows PowerShell 配置

**首次配置（永久保存）：**

```powershell
# 添加到 PowerShell Profile
Add-Content $PROFILE @"

# Kamatera 运维配置
`$env:KAMATERA_HOST = '104.238.213.119'
`$env:KAMATERA_KEY = "`$env:USERPROFILE\.ssh\kamatera"
"@

# 重新加载 Profile
. $PROFILE
```

**临时配置（当前会话）：**

```powershell
$env:KAMATERA_HOST = "104.238.213.119"
$env:KAMATERA_KEY = "$env:USERPROFILE\.ssh\kamatera"
```

### SSH 密钥

密钥文件位置:
- 私钥: `C:\Users\<用户名>\.ssh\kamatera`
- 公钥: `C:\Users\<用户名>\.ssh\kamatera.pub`

---

## 日常运维命令

### 使用 ops_logs.py 脚本

```powershell
cd c:\work\code\crewAI

# 查看服务状态
python scripts\ops_logs.py status

# 实时查看日志
python scripts\ops_logs.py tail

# 查看最近 200 行日志
python scripts\ops_logs.py recent -n 200

# 查看错误日志
python scripts\ops_logs.py errors

# 搜索特定内容
python scripts\ops_logs.py search "用户名"

# 查看 LLM 调用日志
python scripts\ops_logs.py llm

# 查看消息处理日志
python scripts\ops_logs.py messages

# 重启服务
python scripts\ops_logs.py restart

# 查看数据库统计
python scripts\ops_logs.py db-stats
```

### 直接 SSH 命令

```powershell
# SSH 登录
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119

# 远程执行单条命令
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "systemctl status wecom-callback"
```

---

## VM 重启后操作

### 正常情况

**不需要任何操作！** 服务配置为开机自启动 (`systemctl enable`)。

### 验证检查清单

| 检查项 | 命令 | 预期结果 |
| :--- | :--- | :--- |
| 服务状态 | `python scripts\ops_logs.py status` | `active (running)` |
| 健康检查 | `curl http://104.238.213.119:8000/health` | `{"status": "healthy"}` |
| 日志输出 | `python scripts\ops_logs.py tail` | 正常日志 |

### 如果服务未自动启动

```bash
# SSH 登录后
systemctl start wecom-callback
systemctl status wecom-callback

# 查看启动失败原因
journalctl -u wecom-callback -n 50
```

---

## 故障排查指南

### 常见问题

#### 1. 服务无法启动

```bash
# 检查日志
journalctl -u wecom-callback -n 100

# 检查环境配置
cat /etc/wecom-callback/env

# 手动启动测试
cd /opt/wecom-callback
source venv/bin/activate
python -m uvicorn src.crewai_enterprise.server.wecom_callback:app --host 0.0.0.0 --port 8000
```

#### 2. WeCom 消息无响应

```powershell
# 检查消息接收
python scripts\ops_logs.py search "[RECV]"

# 检查 LLM 调用
python scripts\ops_logs.py llm

# 检查错误
python scripts\ops_logs.py errors
```

#### 3. LLM API 错误

```powershell
# 查看 LLM 错误
python scripts\ops_logs.py search "LLM_ERR"

# 检查 API Key 配置
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "grep API_KEY /etc/wecom-callback/env"
```

#### 4. 数据库问题

```bash
# 检查数据库文件
ls -la /var/lib/wecom-callback/

# 验证数据库完整性
sqlite3 /var/lib/wecom-callback/chat_history.db "PRAGMA integrity_check;"

# 查看最近消息
sqlite3 /var/lib/wecom-callback/chat_history.db "SELECT * FROM chat_messages ORDER BY timestamp DESC LIMIT 10;"
```

### 日志标签速查

| 标签 | 含义 |
| :--- | :--- |
| `[RECV]` | 收到 WeCom 消息 |
| `[ROUTE]` | 消息路由决策 |
| `[PROCESS]` | 开始处理消息 |
| `[LLM_REQ]` | LLM API 请求 |
| `[LLM_RES]` | LLM API 响应 |
| `[LLM_ERR]` | LLM API 错误 |
| `[SENT]` | 消息发送成功 |
| `[WEBHOOK_ERR]` | Webhook 发送失败 |
| `[FATAL]` | 严重错误 |
| `[FILE]` | 文件消息处理 |
| `[CLEAR]` | 清空上下文命令 |

---

## 日志管理

### 日志文件

| 文件 | 用途 |
| :--- | :--- |
| `/var/log/wecom-callback/wecom_callback.log` | 全部日志 |
| `/var/log/wecom-callback/wecom_callback_error.log` | 仅错误 |

### 日志轮转

日志自动轮转配置：
- 最大文件大小: 10MB
- 保留备份数: 5 个
- 自动压缩: 否

### 清理旧日志

```bash
# 删除 7 天前的日志备份
find /var/log/wecom-callback/ -name "*.log.*" -mtime +7 -delete
```

---

## 数据库维护

### 查看统计

```powershell
python scripts\ops_logs.py db-stats
```

### 手动查询

```bash
sqlite3 /var/lib/wecom-callback/chat_history.db

# 常用 SQL
.tables                                    # 列出所有表
SELECT COUNT(*) FROM chat_messages;        # 消息总数
SELECT role, COUNT(*) FROM chat_messages GROUP BY role;  # 按角色统计
SELECT * FROM chat_messages ORDER BY timestamp DESC LIMIT 20;  # 最近消息
```

### 数据库备份

```bash
# 创建备份
cp /var/lib/wecom-callback/chat_history.db /var/lib/wecom-callback/chat_history_$(date +%Y%m%d).db.bak

# 下载到本地
scp -i ~/.ssh/kamatera root@104.238.213.119:/var/lib/wecom-callback/chat_history.db ./backup/
```

### 清理旧数据

```sql
-- 删除 30 天前的消息
DELETE FROM chat_messages WHERE timestamp < datetime('now', '-30 days');

-- 压缩数据库
VACUUM;
```

---

## 部署与更新

### 首次部署

```powershell
# 1. 复制部署脚本
scp -i $env:USERPROFILE\.ssh\kamatera scripts\deploy_kamatera.sh root@104.238.213.119:/tmp/

# 2. SSH 登录
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119

# 3. 运行部署
bash /tmp/deploy_kamatera.sh

# 4. 编辑配置
nano /etc/wecom-callback/env

# 5. 重启服务
systemctl restart wecom-callback
```

### 代码更新

```bash
cd /opt/wecom-callback
git pull origin main
systemctl restart wecom-callback
```

### 依赖更新

```bash
cd /opt/wecom-callback
source venv/bin/activate
pip install -r requirements-server.txt --upgrade
systemctl restart wecom-callback
```

### 回滚

```bash
cd /opt/wecom-callback
git log --oneline -10                    # 查看历史
git reset --hard <commit-hash>           # 回滚到指定版本
systemctl restart wecom-callback
```

---

## 监控告警

### 手动健康检查

```powershell
# 从本地检查
Invoke-RestMethod http://104.238.213.119:8000/health
```

### 设置定时监控 (可选)

在本地 Windows 上创建计划任务:

```powershell
# 创建监控脚本
@"
`$response = Invoke-RestMethod -Uri 'http://104.238.213.119:8000/health' -TimeoutSec 10 -ErrorAction SilentlyContinue
if (`$response.status -ne 'healthy') {
    Write-Host "WeCom Callback 服务异常!" -ForegroundColor Red
    # 可添加邮件/企业微信告警
}
"@ | Out-File -FilePath scripts\health_check.ps1 -Encoding UTF8
```

---

## 联系方式

如遇无法解决的问题，请联系：

- 开发团队: [team@example.com]
- 紧急热线: [电话]

---

*文档更新时间: 2025-12-26*
