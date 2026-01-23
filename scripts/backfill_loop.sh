#!/bin/bash
cd /opt/wecom-callback
source /etc/wecom-callback/env
export DISABLE_OCR=true
export PYTHONPATH=/opt/wecom-callback
export PYTHONUNBUFFERED=1
LOG_FILE=/var/log/wecom-callback/backfill_loop.log

echo "Starting backfill loop at $(date)" > $LOG_FILE
# Fix for potential permission issues
chmod 666 $LOG_FILE

while true; do
    echo "--- Batch Start at $(date) ---" >> $LOG_FILE
    # Clear lock if it exists
    rm -f /var/lib/wecom-callback/archive_sync.lock
    # Run the worker
    /opt/wecom-callback/venv/bin/python scripts/archive_sync_worker.py >> $LOG_FILE 2>&1
    # Check result
    RESULT=$(tail -n 1 $LOG_FILE)
    if [[ $RESULT == *'"processed": 0'* ]]; then
        echo "No more messages discovered. Sleeping 10s..." >> $LOG_FILE
        sleep 10
    else
        echo "Batch finished, moving to next..." >> $LOG_FILE
        sleep 1
    fi
done
