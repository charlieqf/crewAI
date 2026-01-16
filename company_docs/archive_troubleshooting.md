# WeCom 会话存档 Troubleshooting 指南

> ⚠️ **已知问题 (2026-01-17)**:
> 
> **SDK 媒体下载问题**: 所有二进制文件（docx/xlsx/pdf/png/jpg）下载后损坏无法打开。
> - 纯文本文件（txt/html/md/py）：✅ 正常
> - 二进制文件（docx/xlsx/pdf/png/jpg）：❌ 文件损坏（即使文件大小显示正确）
> - **根因**: SDK `GetMediaData` 返回的数据未正确解密
> 
> **浏览器编码问题**: 中文文件在浏览器中可能显示乱码，需设置 UTF-8 编码。

## 常见问题与解决方案

### 1. 会话存档停止同步（Stale Lock）

**症状**: 日志显示 `[ARCHIVE_SYNC] Existing sync lock detected; skipping spawn`

**诊断命令**:
```bash
# 检查锁文件
ssh root@104.238.213.119 "ls -la /var/lib/wecom-callback/archive_sync.lock"
# 检查锁文件内容（PID）
ssh root@104.238.213.119 "cat /var/lib/wecom-callback/archive_sync.lock"
# 检查进程是否存在
ssh root@104.238.213.119 "kill -0 <PID> 2>&1 && echo 'alive' || echo 'dead'"
```

**解决方案**:
```bash
# 删除过期锁文件
ssh root@104.238.213.119 "rm /var/lib/wecom-callback/archive_sync.lock"
```

---

### 2. 图片/文件只有几字节

**症状**: Qiniu 上的图片返回 `content-length: 8`

**诊断命令**:
```bash
# 检查文件大小
ssh root@104.238.213.119 "curl -sI 'https://wecomfile.medmeeting.com/<path>' | head -10"
# 检查数据库记录的文件大小
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT file_size, file_uri FROM chat_files ORDER BY created_at DESC LIMIT 5;'"
```

**原因**: WeCom 的 `sdkfileid` 有效期只有 **3 天**。过期后 SDK 的 `GetMediaData` 返回 `is_finish=1` 并只给出几个字节。

**日志特征**:
```
INFO: Downloading image: xxx (249224 bytes)
INFO: Downloaded 4 bytes, type=image/jpeg
```

**为什么 HTML 文件正常**:
- HTML 文件是 AI Bot 本地生成的（如 daily_report.html）
- 不经过 WeCom SDK 下载，直接上传到七牛

**预防**: 设置每日定时同步（见下方 cron 配置）

---

### 3. 消息缺失（Seq Gap）

**症状**: 某几天的消息在 Archive Viewer 中看不到

**诊断命令**:
```bash
# 检查消息日期分布
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT date(created_at) as dt, COUNT(*) FROM archived_messages GROUP BY dt ORDER BY dt DESC LIMIT 10;'"
# 检查当前 cursor
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT * FROM archive_cursor;'"
# 检查 seq 连续性
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT seq, created_at FROM archived_messages WHERE seq BETWEEN 7000 AND 7100 ORDER BY seq;'"
```

**手动补数**:
```bash
# 从指定 seq 开始重新同步
ssh root@104.238.213.119 "rm -f /var/lib/wecom-callback/archive_sync.lock && /opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py <START_SEQ>"
```

---

### 4. 服务启动失败

**症状**: `systemctl status wecom-callback` 显示 failed

**诊断命令**:
```bash
ssh root@104.238.213.119 "journalctl -u wecom-callback -n 50 --no-pager | grep -iE '(error|import|module)'"
# 测试 Python 导入
ssh root@104.238.213.119 "cd /opt/wecom-callback && /opt/wecom-callback/venv/bin/python -c 'from src.crewai_enterprise.server.wecom_callback import app; print(app)'"
```

---

## 常用运维命令

### 查看服务状态
```bash
ssh root@104.238.213.119 "systemctl status wecom-callback --no-pager | head -15"
```

### 查看实时日志
```bash
ssh root@104.238.213.119 "journalctl -u wecom-callback -f"
```

### 重启服务
```bash
ssh root@104.238.213.119 "systemctl restart wecom-callback"
```

### 部署最新代码
```bash
git push origin feat-wecom
ssh root@104.238.213.119 "cd /opt/wecom-callback && git fetch origin && git reset --hard origin/feat-wecom && systemctl restart wecom-callback"
```

### 健康检查
```bash
ssh root@104.238.213.119 "curl -s http://localhost:8000/health"
```

---

## 数据库查询

### 统计概览
```bash
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT COUNT(*) as messages FROM archived_messages; SELECT COUNT(*) as files FROM chat_files;'"
```

### 最新消息
```bash
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT seq, created_at, msgtype FROM archived_messages ORDER BY seq DESC LIMIT 10;'"
```

### 搜索消息内容
```bash
ssh root@104.238.213.119 "sqlite3 /var/lib/wecom-callback/chat_history.db \"SELECT seq, created_at, content FROM archived_messages WHERE content LIKE '%关键词%' LIMIT 5;\""
```

---

## 设置每日自动同步

添加 cron 任务：
```bash
ssh root@104.238.213.119 "echo '0 0 * * * /opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py \$(sqlite3 /var/lib/wecom-callback/chat_history.db \"SELECT seq FROM archive_cursor WHERE id=1\") >> /var/log/wecom-callback/archive_cron.log 2>&1' | crontab -"
```

---

## WeCom API 限制

| 限制 | 值 |
|------|-----|
| sdkfileid 有效期 | 3 天 |
| 消息保留期 | 7 天 |
| 单次拉取上限 | 500 条 |

---

*最后更新: 2026-01-17*
