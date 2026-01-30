#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="${1:-}"
LIMIT="${2:-10}"
if [[ -z "$SESSION_ID" ]]; then
  echo "usage: $0 SESSION_ID [LIMIT]" >&2
  exit 1
fi

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
