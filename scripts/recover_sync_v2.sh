#!/bin/bash
export ENV_PATH=/etc/wecom-callback/env
cd /opt/wecom-callback
echo "Starting catch-up sync..."
while :; do
    result=$(./venv/bin/python scripts/archive_sync_worker.py 0)
    echo $result
    if [[ $result != *"\"processed\": 100"* ]]; then
        break
    fi
done
echo "Starting message cleanup..."
echo "DELETE FROM archived_messages WHERE msgtype='unknown' AND content LIKE '%\"action\":%'; " > /tmp/cleanup.sql
sqlite3 /var/lib/wecom-callback/chat_history.db < /tmp/cleanup.sql
echo "Cleanup done."
echo "Remaining unknowns count:"
sqlite3 /var/lib/wecom-callback/chat_history.db "SELECT COUNT(*) FROM archived_messages WHERE msgtype='unknown';"
