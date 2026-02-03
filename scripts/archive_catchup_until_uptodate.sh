#!/usr/bin/env bash
set -euo pipefail

HOST=${1:-104.238.213.119}
USER=${2:-root}
KEY=${3:-/c/Users/rdpuser/.ssh/kamatera}
FROM=${4:-2026-02-01 00:00:00}
MAX_BATCHES=${5:-50}
NO_PROGRESS_LIMIT=${6:-2}

run_local=0
if [ "${HOST}" = "localhost" ] || [ "${HOST}" = "127.0.0.1" ]; then
  run_local=1
fi
if [ -f /etc/wecom-callback/env ] && [ -x /opt/wecom-callback/venv/bin/python ]; then
  run_local=1
fi

if [ -z "$FROM" ]; then
  echo "Usage: $0 <host> <user> <key> <from-date> [max-batches] [no-progress-limit]"
  echo "Example: $0 104.238.213.119 root /c/Users/rdpuser/.ssh/kamatera '2026-02-01 00:00:00' 50 2"
  exit 1
fi

no_progress=0
prev_seq=""

for i in $(seq 1 "$MAX_BATCHES"); do
  echo "--- batch $i ---"
  run_cmd="set -a; source /etc/wecom-callback/env; set +a; ARCHIVE_SYNC_LOCK=/tmp/archive_sync_$i.lock /opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py 0 '$FROM'"
  cursor_cmd="sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT seq, updated_at FROM archive_cursor WHERE id = 1;'"
  latest_cmd="sqlite3 /var/lib/wecom-callback/chat_history.db 'SELECT MAX(created_at) FROM archived_messages;'"
  if [ "$run_local" -eq 1 ]; then
    bash -lc "$run_cmd"
    cursor=$(bash -lc "$cursor_cmd")
    latest=$(bash -lc "$latest_cmd")
  else
    ssh -i "$KEY" "$USER@$HOST" "bash -lc '$run_cmd'"
    cursor=$(ssh -i "$KEY" "$USER@$HOST" "bash -lc \"$cursor_cmd\"")
    latest=$(ssh -i "$KEY" "$USER@$HOST" "bash -lc \"$latest_cmd\"")
  fi
  echo "$cursor"
  echo "$latest"

  if [ "$cursor" = "$prev_seq" ]; then
    no_progress=$((no_progress+1))
  else
    no_progress=0
  fi
  prev_seq="$cursor"

  if [ "$no_progress" -ge "$NO_PROGRESS_LIMIT" ]; then
    echo "No progress for $NO_PROGRESS_LIMIT batches; stopping."
    exit 0
  fi
done

echo "Reached max batches: $MAX_BATCHES"
