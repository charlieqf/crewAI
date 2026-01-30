#!/usr/bin/env bash
set -euo pipefail

MINUTES="${1:-10}"
LINES="${2:-200}"
LIMIT="${3:-10}"

echo "== Latest OpenCode log =="
ls -t /root/.local/share/opencode/log/*.log | head -1

echo "== Tail OpenCode log =="
tail -n "$LINES" "$(ls -t /root/.local/share/opencode/log/*.log | head -1)"

echo "== Tail wecom-callback log =="
journalctl -u wecom-callback --since "${MINUTES} min ago" --no-pager | tail -n 200

echo "== Session status =="
curl -s http://localhost:4096/session/status | python3 -m json.tool

echo "== Latest session messages =="
SESSION_ID="$(journalctl -u wecom-callback --since "${MINUTES} min ago" --no-pager | grep -i OPENCODE | grep "Starting prompt" | tail -1 | sed -E 's/.*session=([^ ]+).*/\1/')"
if [[ -n "$SESSION_ID" ]]; then
  echo "session_id=$SESSION_ID"
  LIMIT="$LIMIT" curl -s "http://localhost:4096/session/${SESSION_ID}/message" | python3 -c \
    'import sys, json, os
msgs = json.load(sys.stdin)
limit = int(os.environ.get("LIMIT", "10"))
print("total", len(msgs))
for m in msgs[-limit:]:
    info = m.get("info", {})
    role = info.get("role")
    mid = info.get("id")
    pid = info.get("parentID") or info.get("parentId")
    text = ""
    for p in m.get("parts", []):
        if p.get("type") == "text":
            text = p.get("text", "")[:120].replace("\n", " ")
            break
    print(role, mid, "parent", pid, "text", text)
'
else
  echo "No recent session found in wecom-callback logs."
fi
