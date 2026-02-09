# OpenCode In-Place Upgrade Runbook (Kamatera)

Goal: upgrade OpenCode running in service mode on the Kamatera VM, verify integration compatibility (API + storage layout), and support fast rollback.

## Scope / Background

- OpenCode service: `opencode.service`
- Port: `127.0.0.1:4096`
- Unit file: `/etc/systemd/system/opencode.service`
- Env file: `/etc/wecom-callback/env` (loaded by systemd unit)
- Working directory: `/opt/oh-my-opencode`
- OpenCode storage: `/root/.local/share/opencode/storage`
- Integration coupling points:
  - HTTP API used by our server: `/config`, `/session/status`, `/session/abort`, `/session/{id}/message`
  - On-disk storage read by our worker: `storage/message/<session_id>/*.json` + `storage/part/<message_id>/*.json`

## Version Pins

- Target version: `1.1.53`
- Rollback version: record the current version before upgrade (expected `1.1.47`)

Do not upgrade to "latest" without pinning.

## Step 1: Preflight Snapshot (Read-only)

Run on VM:

1) Service status + version

```bash
systemctl status opencode --no-pager
opencode --version || true
/usr/bin/opencode --version || true
```

2) Confirm systemd unit wiring

```bash
systemctl show opencode --no-pager -p ExecStart -p FragmentPath -p WorkingDirectory -p EnvironmentFile
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/systemd/system/opencode.service')
print(p.read_text() if p.exists() else 'missing')
PY
```

3) Confirm port + basic endpoints

```bash
ss -ltnp | grep 4096 || true
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4096/config
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4096/session/status
```

4) Confirm storage dirs exist

```bash
ls -la /root/.local/share/opencode/storage
```

5) Determine install method + package name (critical for rollback)

```bash
command -v npm || true
npm -v || true
npm ls -g --depth=0 | grep -i opencode || true
ls -la /usr/bin/opencode
file /usr/bin/opencode || true
```

Pass criteria:

- `/config` and `/session/status` return HTTP 200 and JSON content-type
- You have written down current OpenCode version and how it was installed (npm package name/version)

## Step 2: Backups (Small + Fast)

We back up config + unit + env (NOT the full storage directory).

```bash
TS=$(date +%F_%H%M%S)
mkdir -p /root/opencode-backups/$TS

cp -a /etc/systemd/system/opencode.service /root/opencode-backups/$TS/
cp -a /etc/wecom-callback/env /root/opencode-backups/$TS/

tar -czf /root/opencode-backups/$TS/opencode-config.tgz /root/.config/opencode

journalctl -u opencode --since -30min --no-pager > /root/opencode-backups/$TS/opencode-journal-before.log
echo "backup dir: /root/opencode-backups/$TS"
```

Pass criteria:

- backup folder exists and contains `opencode.service` and `opencode-config.tgz`

## Step 3: Upgrade OpenCode (In-place)

If installed via npm as `opencode-ai`:

```bash
npm view opencode-ai@1.1.53 version
npm i -g opencode-ai@1.1.53
hash -r
opencode --version
```

If it is NOT `opencode-ai`, stop and use the matching upgrade method (do not guess).

Pass criteria:

- `opencode --version` shows `1.1.53`

## Step 4: Restart OpenCode + Basic Health Checks

```bash
systemctl restart opencode
systemctl is-active opencode
ss -ltnp | grep 4096 || true

curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4096/config
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4096/session/status

journalctl -u opencode --since -10min --no-pager | tail -n 200
```

Pass criteria:

- service active + port listening
- endpoints return HTTP 200 JSON

## Step 5: API Contract Smoke Test (Local)

Create a session:

```bash
SID=$(curl -fsS -X POST "http://127.0.0.1:4096/session?directory=/opt/oh-my-opencode" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "$SID"
```

Send a short message:

```bash
curl -fsS -X POST "http://127.0.0.1:4096/session/$SID/message?directory=/opt/oh-my-opencode" \
  -H "Content-Type: application/json" \
  -d '{"noReply":false,"parts":[{"type":"text","text":"Reply with exactly: OK"}]}' \
  >/dev/null
```

Abort endpoint (important for our integration’s busy-session handling):

```bash
curl -fsS -X POST "http://127.0.0.1:4096/session/abort" \
  -H "Content-Type: application/json" \
  -d "{\"sessionID\":\"$SID\"}" \
  >/dev/null
```

Pass criteria:

- all calls return HTTP 200
- abort does not crash `opencode.service`

## Step 6: Storage Compatibility Smoke Test

Confirm the session message directory exists and gets JSON:

```bash
ls -la "/root/.local/share/opencode/storage/message/$SID" | head -n 50
```

Confirm message JSON still has top-level `id` / `role` and that `part/<message_id>/` exists:

```bash
python3 - <<'PY'
import json
from pathlib import Path
import os

sid = os.environ.get('SID')
if not sid:
    raise SystemExit('SID env var not set')
msg_dir = Path('/root/.local/share/opencode/storage/message') / sid
files = sorted(msg_dir.glob('*.json'))
if not files:
    raise SystemExit('No message json files found')
f = files[-1]
obj = json.loads(f.read_text(encoding='utf-8'))
mid = obj.get('id')
role = obj.get('role')
print('sample_file', f.name)
print('role', role)
print('has_id', bool(mid))
if mid:
    part_dir = Path('/root/.local/share/opencode/storage/part') / mid
    print('part_dir_exists', part_dir.exists())
PY
```

Pass criteria:

- `message/$SID` exists with `*.json`
- newest message json has `id` and `role`
- corresponding `part/<message_id>` directory exists

## Step 7: Full Integration Verification (WeCom /task)

Run one small task and confirm output appears end-to-end.

- Trigger: send a WeCom message `/task say OK and stop` (or any tiny prompt)
- Confirm task worker runs:

```bash
journalctl -u wecom-task-worker --since -10min --no-pager | tail -n 200
```

- Confirm task page shows assistant output incrementally
- Confirm OpenCode stayed healthy:

```bash
systemctl is-active opencode
journalctl -u opencode --since -10min --no-pager | tail -n 200
```

Pass criteria:

- task output appears on the task page
- no storage reader errors
- no stuck/busy loops that prevent subsequent prompts

## Step 8: Rollback (Fast)

Rollback triggers:

- service won’t stay up
- endpoints fail
- storage layout breaks our reader
- task output stops appearing

If installed via npm as `opencode-ai`:

```bash
npm i -g opencode-ai@<previous_version>
hash -r
opencode --version
systemctl restart opencode
systemctl is-active opencode
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:4096/config
```

If config/unit need restore:

- restore from `/root/opencode-backups/$TS/`

```bash
systemctl daemon-reload
systemctl restart opencode
```

Pass criteria:

- previous version restored, service active, endpoints OK

## Notes / Pitfalls

- If running SSH commands from a local shell, avoid local `$()` expansions. Prefer running commands directly on the VM, or wrap scripts in a remote heredoc carefully.
- We intentionally do NOT roll back storage; only binary/config/service.
