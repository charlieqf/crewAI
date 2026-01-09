#!/usr/bin/env python3
"""
Backfill script for WeCom Archive Images.
Finds existing image messages in the database that haven't been processed
and uploads them to Qiniu.
"""
import os
import json
import logging
import sqlite3
import sys

# Add project to path
sys.path.insert(0, "/opt/wecom-callback")

# Reuse logic from worker
from scripts.archive_sync_worker import (
    WeWorkFinanceSDK, 
    process_image_message, 
    load_env,
    init_db
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def backfill():
    load_env("/etc/wecom-callback/env")
    
    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("ARCHIVE_SECRET")
    db_path = os.getenv("ARCHIVE_DB_PATH", os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db"))
    
    if not all([corp_id, secret, db_path]):
        logger.error("Missing configuration. Check /etc/wecom-callback/env")
        return

    # [FIX] Medium finding: Ensure schema is initialized
    init_db(db_path)
    
    # Initialize SDK
    sdk = WeWorkFinanceSDK()
    if not sdk.init(corp_id, secret):
        logger.error("Failed to initialize SDK")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Find image messages without chat_files records
    cursor.execute("""
        SELECT m.id, m.msgid, m.content 
        FROM archived_messages m
        LEFT JOIN chat_files f ON m.msgid = f.msgid
        WHERE m.msgtype = 'image' AND f.id IS NULL
        ORDER BY m.id DESC
    """)
    
    to_process = cursor.fetchall()
    logger.info(f"Found {len(to_process)} images to backfill")
    
    processed = 0
    failed = 0
    
    for row in to_process:
        db_id, msgid, content_json = row
        try:
            msg_data = json.loads(content_json)
            logger.info(f"Processing image {msgid} (DB ID: {db_id})")
            
            if process_image_message(sdk, msg_data, cursor):
                processed += 1
                # Commit every 10 messages
                if processed % 10 == 0:
                    conn.commit()
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Error processing {msgid}: {e}")
            failed += 1
            
    conn.commit()
    conn.close()
    
    logger.info(f"Backfill complete: {processed} processed, {failed} failed")

if __name__ == "__main__":
    backfill()
