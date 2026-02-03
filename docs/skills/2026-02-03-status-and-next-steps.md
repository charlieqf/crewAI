# Status & Next Steps (2026-02-03)

## What We Did (Recent Rounds)

- **Fixed OpenCode model selection** to use `opencode/claude-sonnet-4-5` and ensured OpenCode runs without OMO defaults.
- **Stabilized OpenCode** after invalid JSON crashes in `/root/.config/opencode/opencode.json`.
- **Task worker logging improved** to show both agent-config and default model.
- **Resolved false “missing file” warnings** by checking actual file existence before warning.
- **Verified task pipeline health** (task 35/37): session outputs, file sync, and model usage.
- **Archive catch-up status**: global cursor advanced to seq `45971` (2026‑02‑03), but specific room `wrQakDCgAAa-wxaHCLgJ929glNlcKfBg` still lags after seq 45657 → likely upstream archive scope issue.
- **Skill setup in worktree**: copied required skills into `.opencode/skill/<name>/SKILL.md` in worktree; validated frontmatter names; `opencode debug skill` confirms discovery.

## Current State

### Code / Worktree

- **Active worktree**: `C:\work\code\crewAI\.worktrees\opencode-task-context`
- **Branch**: `feat/opencode-task-context`
- **Latest commit**: `dfa2922f` (fix: avoid false missing file warnings)

### Services (VM)

- **wecom-callback**: running
- **wecom-task-worker**: running
- **opencode**: running on 127.0.0.1:4096

### Skills (Worktree discovery)

Required skills are in:

- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\opencode-debug\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\opencode-task-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-archive-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-daily-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-opencode-task-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\deploy-verify\SKILL.md`

`opencode debug skill` confirms these are discoverable when OpenCode is launched from the worktree.

## Known Issues

- **Room lag**: `wrQakDCgAAa-wxaHCLgJ929glNlcKfBg` latest archived message is still `2026-02-02 21:46:14` (seq 45657) despite global cursor moving forward. Indicates **WeCom Finance API stream likely missing messages for that room** (scope/permission issue).
- **Task 37**: System “missing file” warnings were previously false positives. Now fixed in worker; new runs should not warn if file exists.

## What To Do Next

### 1) Start OpenCode in the worktree

```bash
cd C:\work\code\crewAI\.worktrees\opencode-task-context
opencode
```

This ensures the Skill tool loads from `.opencode/skill` in this worktree.

### 2) Verify skills are loaded

```bash
opencode debug skill
```

Then try loading the 6 required skills via the Skill tool.

### 3) Re-test Task 37 re-save behavior

Send a new WeCom message (e.g., “重新保存 analysis.html”) and confirm:

- No false “missing file” system warning
- `analysis.html` exists under `/opt/oh-my-opencode/tasks/37`

### 4) Investigate archive gap (room-specific)

Likely WeCom Finance API scope issue. Verify that room/users are included in archive scope, or do a targeted fetch to confirm no messages returned for that room after seq 45657.

## Handy Commands

### Task status/logs/files

```bash
curl -s http://104.238.213.119:8000/api/task/37
curl -s http://104.238.213.119:8000/api/task/37/logs
curl -s http://104.238.213.119:8000/api/task/37/files
```

### Workdir check

```bash
ssh -i ~/.ssh/kamatera root@104.238.213.119 "ls -la /opt/oh-my-opencode/tasks/37"
```

### Archive status

```bash
ssh -i ~/.ssh/kamatera root@104.238.213.119 "pgrep -af archive_sync_worker.py || true"
ssh -i ~/.ssh/kamatera root@104.238.213.119 "python3 - <<'PY'
import sqlite3
from pathlib import Path
db = Path('/var/lib/wecom-callback/chat_history.db')
conn = sqlite3.connect(str(db))
cur = conn.cursor()
cur.execute('SELECT seq, updated_at FROM archive_cursor WHERE id = 1')
print('archive_cursor:', cur.fetchone())
cur.execute('SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM archived_messages')
print('archived_messages:', cur.fetchone())
conn.close()
PY"
```
