#!/usr/bin/env bash
set -euo pipefail

SESSION_ID="${1:-}"
LIMIT="${2:-10}"
MINUTES="${3:-15}"

if [[ -z "$SESSION_ID" ]]; then
  SESSION_ID="$(journalctl -u wecom-callback --since "${MINUTES} min ago" --no-pager \
    | grep -i OPENCODE | grep "Starting prompt" | tail -1 | sed -E 's/.*session=([^ ]+).*/\1/')"
fi

if [[ -z "$SESSION_ID" ]]; then
  echo "No session found in wecom-callback logs (last ${MINUTES} min)."
  exit 1
fi

echo "session_id=$SESSION_ID"
curl -s "http://localhost:4096/session/${SESSION_ID}/message" | python3 -c \
  "import json,sys
msgs=json.load(sys.stdin)
users=[m for m in msgs if m.get('info',{}).get('role')=='user']
if not users:
    print('no user messages')
    raise SystemExit(0)
last_user=max(users, key=lambda m: m.get('info',{}).get('time',{}).get('created') or 0)
uid=last_user.get('info',{}).get('id')
utext=''
for p in last_user.get('parts',[]):
    if p.get('type')=='text':
        utext=p.get('text','').replace('\\n',' ')
        break
assist=[m for m in msgs if (m.get('info',{}).get('parentID')==uid or m.get('info',{}).get('parentId')==uid)]
max_text=''
last_text=''
last_types=[]
for m in assist:
    parts=m.get('parts',[])
    types=[p.get('type') for p in parts]
    text=''.join([p.get('text','') for p in parts if p.get('type')=='text'])
    if text:
        last_text=text
    if len(text)>len(max_text):
        max_text=text
    last_types=types
print('last_user', uid, 'text', utext[:140])
print('assistant_count', len(assist))
print('assistant_last_types', last_types)
print('assistant_longest_len', len(max_text))
print('assistant_longest_text', max_text[:200].replace('\\n',' '))
print('assistant_last_text', last_text[:200].replace('\\n',' '))"
