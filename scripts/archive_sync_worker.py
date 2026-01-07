#!/usr/bin/env python3
"""
WeCom Archive Sync Worker - Standalone subprocess script.

This script is designed to be run via subprocess to isolate the C SDK from
the main uvicorn process, avoiding memory management conflicts.

Usage:
    python archive_sync_worker.py [start_seq]

Output (stdout): JSON with {"status": "ok", "new_max_seq": N} or {"status": "error", "message": "..."}
"""
import os
import sys
import json
import logging
import sqlite3

# Add project to path
sys.path.insert(0, "/opt/wecom-callback")

def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# Load env before importing SDK
load_env("/etc/wecom-callback/env")

from src.crewai_enterprise.utils.wework_finance_sdk import WeWorkFinanceSDK
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def sync(start_seq: int):
    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("ARCHIVE_SECRET")
    priv_key_path = os.getenv("ARCHIVE_RSA_PRIVATE_KEY_PATH", "/opt/wecom-callback/keys/archive_private_key.pem")
    db_path = os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
    
    if not corp_id or not secret:
        return {"status": "error", "message": "Missing WECOM_CORP_ID or ARCHIVE_SECRET"}

    # Initialize SDK
    sdk = WeWorkFinanceSDK()
    if not sdk.init(corp_id, secret):
        return {"status": "error", "message": "Failed to initialize SDK"}

    # Pull messages
    chat_data = sdk.get_chat_data(start_seq, limit=100)
    if not chat_data:
        return {"status": "ok", "new_max_seq": start_seq, "processed": 0}

    # Load private key
    try:
        with open(priv_key_path, "rb") as f:
            priv_key = RSA.importKey(f.read())
    except Exception as e:
        return {"status": "error", "message": f"Failed to load private key: {e}"}
    
    cipher_rsa = PKCS1_v1_5.new(priv_key)
    new_max_seq = start_seq
    processed = 0
    
    for msg in chat_data:
        try:
            # RSA Decrypt
            encrypted_key = base64.b64decode(msg['encrypt_random_key'])
            random_key_bytes = cipher_rsa.decrypt(encrypted_key, None)
            if not random_key_bytes:
                continue
            random_key = random_key_bytes.decode('utf-8')
            
            # SDK Decrypt
            decrypted_json = sdk.decrypt_data(random_key, msg['encrypt_chat_msg'])
            if not decrypted_json:
                continue
            
            decrypted_msg = json.loads(decrypted_json)
            
            # Log message type for now
            msg_type = decrypted_msg.get("msgtype", "unknown")
            logger.info(f"Processed msg seq={msg['seq']} type={msg_type}")
            
            # TODO: Handle file downloads here if needed
            
            new_max_seq = max(new_max_seq, msg['seq'])
            processed += 1
        except Exception as e:
            logger.error(f"Error processing msg {msg.get('seq')}: {e}")

    # Update cursor in DB
    if new_max_seq > start_seq:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS archive_cursor (id INTEGER PRIMARY KEY, seq INTEGER, updated_at TEXT)")
            cursor.execute("INSERT OR IGNORE INTO archive_cursor (id, seq) VALUES (1, 0)")
            cursor.execute("UPDATE archive_cursor SET seq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (new_max_seq,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update cursor: {e}")

    return {"status": "ok", "new_max_seq": new_max_seq, "processed": processed}

if __name__ == "__main__":
    start_seq = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    result = sync(start_seq)
    print(json.dumps(result))
