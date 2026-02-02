---
name: wecom-opencode-task-ops
description: Troubleshoot WeCom ↔ OpenCode task integration. Use when task pages show missing files, task worker output is empty, /api/task endpoints fail, or when verifying task workdir/file sync and OpenCode session ingestion.
---

# WeCom OpenCode Task Ops

## Workflow

1) Identify the task id and fetch status/logs/files via HTTP.
2) Verify task workdir exists and contains claimed files.
3) Check task worker logs for prompt/send/receive/sync steps.
4) Verify OpenCode session messages if output is missing.

## Defaults

- Task base URL: `http://104.238.213.119:8000`
- Workdir root: `/opt/oh-my-opencode/tasks/<id>`
- Task storage root: `/var/lib/wecom-tasks/<chat_id>/tasks/<id>`
- Services: `wecom-callback`, `wecom-task-worker`

## Checks

- Task status: `curl -s http://104.238.213.119:8000/api/task/<id>`
- Task logs: `curl -s http://104.238.213.119:8000/api/task/<id>/logs`
- Task files: `curl -s http://104.238.213.119:8000/api/task/<id>/files`
- Workdir: `ls -la /opt/oh-my-opencode/tasks/<id>`
- Files dir: `ls -la /var/lib/wecom-tasks/<chat_id>/tasks/<id>/files`
- Worker logs: `journalctl -u wecom-task-worker --since -10min --no-pager`

## Common issues

- **Claimed file missing**: verify workdir; if missing, check OpenCode session output and prompt guardrails.
- **No task output**: verify `opencode_storage_root`, session messages, and `last_seen_message_file`.
- **Sync not happening**: ensure `mirror_session_files` ran and `files/` exists.
