---
name: deploy-verify
description: Commit, push, pull on VM, restart services, verify task status/logs/outputs for WeCom OpenCode tasks. Use when deploying changes or validating task runs.
---

# Deploy & Verify Workflow

## Defaults
- VM host: 104.238.213.119
- VM user: root
- SSH key: ~/.ssh/kamatera
- Repo path on VM: /opt/wecom-callback
- Services: wecom-callback, wecom-task-worker
- Task base URL: http://104.238.213.119:8000

## Commit + Push
1) `git status -sb` and `git diff`
2) Stage only relevant files, excluding planning notes and secrets.
3) Commit with concise message.
4) `git push`.

## Deploy to VM
1) `ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'cd /opt/wecom-callback && git pull'"`
2) Restart services:
   `ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'systemctl restart wecom-callback wecom-task-worker'"`

## Useful Scripts
- `scripts/deploy_kamatera.sh`: full server bootstrap + deploy (first-time or rebuild).
- `scripts/deploy.sh`: generic Ubuntu deployment (not Kamatera-specific).
- `scripts/opencode_debug/oc-diag.sh`: quick server diagnostics.
- `scripts/opencode_debug/oc-session-status.sh`: session status.
- `scripts/opencode_debug/oc-session-messages.sh <session_id>`: session messages.
- `scripts/opencode_debug/oc-log-tail.sh`: OpenCode log tail.

## Verify
### Task status
`curl -s http://104.238.213.119:8000/api/task/<id>`

### Task logs
`curl -s http://104.238.213.119:8000/api/task/<id>/logs`

### Task outputs
`curl -s http://104.238.213.119:8000/api/task/<id>/files`

### Workdir check (optional)
`ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'ls -la /opt/oh-my-opencode/tasks/<id>'"`

## Must Do
- Use commit → push → pull flow (never scp code to VM).
- If `git pull` fails due to local VM changes, ask before `git reset --hard`.
- Confirm task status and outputs after restart.
