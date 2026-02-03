---
name: opencode-task-ops
description: Operate and troubleshoot OpenCode /task workflow on the Kamatera VM. Use when checking task creation/append flow, task worker processing, task page output, file sync behavior, or task storage health.
---

# OpenCode Task Ops

## Workflow

1) Identify task scope: creation, append, worker, storage, or UI.
2) Check task service endpoints and handler flow.
3) Check worker processing and OpenCode session output ingestion.
4) Verify file sync behavior for task workdir.

## Key locations

- Task API + web UI: `src/crewai_enterprise/server/task_service.py`, `src/crewai_enterprise/server/task_viewer.py`
- WeCom command handler: `src/crewai_enterprise/server/handlers/task_handler.py`
- Worker loop: `src/crewai_enterprise/server/task_worker.py`
- Storage + schema: `src/crewai_enterprise/server/task_store.py`
- File sync: `src/crewai_enterprise/server/opencode_file_sync.py`

## Expected behavior

- `/task <text>` creates task, enqueues TaskInput, returns link.
- `/task <id> <text>` appends input to same task.
- Task worker claims inputs, ensures session/workdir, writes TaskMessage.
- Files mirrored into `files/` and listed on task page.

## Checks

- DB schema includes `task`, `task_message`, `task_input`, and `workdir`.
- `TASK_WORKDIR_ROOT` set or default used; per-task dir created.
- `last_seen_message_file` advances as output is consumed.
- `opencode_file_sync` uses `workdir` when provided.

## Script: Safe Python scan (no f-string pitfalls)

Use this when you need to scan a file for `OPENCODE` or `model` references without hitting f-string syntax errors.

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "python3 - <<'PY'
from pathlib import Path
path = Path('/opt/wecom-callback/src/crewai_enterprise/server/task_worker.py')
if not path.exists():
    print('task_worker.py not found')
    raise SystemExit(0)
lines = path.read_text().splitlines()
for i, line in enumerate(lines, 1):
    if 'opencode' in line.lower() or 'model' in line.lower() or 'OPENCODE' in line:
        print('%d: %s' % (i, line))
PY"
```
