#!/usr/bin/env python3
import sys
import os
import subprocess
import sqlite3
import time
import json

# Path to the db and worker
DB_PATH = '/var/lib/wecom-callback/chat_history.db'
WORKER_PATH = '/opt/wecom-callback/scripts/archive_sync_worker.py'
PYTHON_PATH = '/opt/wecom-callback/venv/bin/python'
LOCK_PATH = '/var/lib/wecom-callback/archive_sync.lock'

def get_seq():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60)
        cursor = conn.cursor()
        cursor.execute("SELECT seq FROM archive_cursor WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception as e:
        print(f"Error getting seq: {e}")
        return None

def run_sync():
    print("Starting resilient catch-up sync...")
    
    consecutive_errors = 0
    
    while True:
        # Remove stale lock if any (only if we are sure no other worker is running)
        # In this resilient version, we'll try to be the only one.
        if os.path.exists(LOCK_PATH):
            try:
                os.remove(LOCK_PATH)
            except:
                pass
        
        seq = get_seq()
        if seq is None:
            print("Database locked while reading seq, retrying in 5s...")
            time.sleep(5)
            continue
            
        print(f"Current cursor: {seq}")
        
        # Run worker
        result = subprocess.run([PYTHON_PATH, WORKER_PATH, str(seq)], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Worker failed with code {result.returncode}")
            print(f"ERR: {result.stderr}")
            consecutive_errors += 1
            wait_time = min(60, 5 * consecutive_errors)
            print(f"Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            continue
        
        consecutive_errors = 0
        
        # Check if we processed anything
        try:
            output = result.stdout.strip()
            if not output:
                print("No output from worker, retrying...")
                time.sleep(2)
                continue
                
            lines = output.split('\n')
            # Look for the JSON line which starts with {"status":
            data = None
            for line in reversed(lines):
                if line.strip().startswith('{"status":'):
                    data = json.loads(line)
                    break
            
            if not data:
                print("No JSON status found in worker output, retrying...")
                time.sleep(2)
                continue
                
            processed = data.get("processed", 0)
            new_seq = data.get("new_max_seq", seq)
            
            if processed == 0 and new_seq == seq:
                # This usually means WeCom has no more messages AT THIS MOMENT.
                # But we might be in a gap. However, the worker loops until it finds data or hits head.
                # If we get 0, we can wait a bit longer.
                print("No more messages found by worker. Waiting 10s before checking again...")
                time.sleep(10)
                continue
                
            print(f"Processed {processed} messages. New seq: {new_seq}")
            
        except Exception as e:
            print(f"Failed to parse output: {e}")
            time.sleep(5)
            continue
            
        time.sleep(1)

if __name__ == "__main__":
    run_sync()
