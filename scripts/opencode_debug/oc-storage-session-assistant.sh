#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="${1:-}"
STORAGE="${2:-/root/.local/share/opencode/storage}"

export SESSION_ID
export STORAGE

if [[ -z "$SESSION_ID" ]]; then
  echo "Usage: $0 <session_id> [storage_root]" >&2
  exit 2
fi

python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

session_id = os.environ.get("SESSION_ID")
storage = os.environ.get("STORAGE")

msg_dir = Path(storage) / "message" / session_id
part_dir = Path(storage) / "part"

if not msg_dir.exists():
    print(f"message dir not found: {msg_dir}", file=sys.stderr)
    raise SystemExit(1)

def read_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

msgs = []
for p in sorted(msg_dir.glob("*.json")):
    try:
        d = read_json(p)
    except Exception:
        continue
    if d.get("role") == "assistant":
        msgs.append(d)

print(f"assistant_messages={len(msgs)} session={session_id}")
for m in msgs:
    mid = m.get("id")
    created = m.get("time", {}).get("created")
    pdir = part_dir / mid
    parts = []
    if pdir.exists():
        for pp in sorted(pdir.glob("*.json")):
            try:
                pd = read_json(pp)
            except Exception:
                continue
            parts.append(pd)
    part_types = [p.get("type") for p in parts]
    text_preview = ""
    for p in parts:
        if p.get("type") == "text":
            text_preview = (p.get("text") or "")[:200].replace("\n", " ")
            break
    print(f"- msg={mid} created={created} parts={part_types} text='{text_preview}'")
PY
