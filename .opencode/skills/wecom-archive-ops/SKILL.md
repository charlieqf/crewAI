---
name: wecom-archive-ops
description: Troubleshoot WeCom archive sync worker. Use when archive cursor lags, archive sync reports "already running", or archived messages are stale. Covers lock handling, env loading, and verification.
---

# WeCom Archive Ops

## Workflow

1) Check running process + lock file.
2) Read archive cursor and latest archived timestamp.
3) If stale and no active process, clear stale lock then run catch-up.
4) Re-check cursor + latest timestamp to confirm progress.

## Status & Progress

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "pgrep -af archive_sync_worker.py || true"
```

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "ls -la /opt/wecom-callback/scripts/archive_sync.lock && cat /opt/wecom-callback/scripts/archive_sync.lock || true"
```

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "python3 - <<'PY'
import sqlite3
from pathlib import Path

db = Path('/var/lib/wecom-callback/chat_history.db')
if not db.exists():
    print('chat_history.db not found')
    raise SystemExit(0)
conn = sqlite3.connect(str(db))
cur = conn.cursor()
cur.execute('SELECT seq, updated_at FROM archive_cursor WHERE id = 1')
print('archive_cursor:', cur.fetchone())
cur.execute('SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM archived_messages')
print('archived_messages:', cur.fetchone())
conn.close()
PY"
```

## Catch-up (one-shot)

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "bash -lc 'set -a; source /etc/wecom-callback/env; set +a; /opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py 0'"
```

## Catch-up (batch, background-safe)

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "bash -lc 'cd /opt/wecom-callback && nohup scripts/archive_catchup_until_uptodate.sh 104.238.213.119 root ~/.ssh/kamatera "'"'2026-02-01 00:00:00'"'" 200 3 > /var/log/archive_catchup_until_uptodate.log 2>&1 &'"
```

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "tail -n 50 /var/log/archive_catchup_until_uptodate.log"
```

## Notes

- Lock path defaults to `/opt/wecom-callback/scripts/archive_sync.lock`.
- If "already running" but no process exists, delete the lock file then re-run.
- Use python-based status queries above to avoid sqlite3 dependency issues on the VM.
