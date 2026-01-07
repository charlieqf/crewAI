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
import hashlib
from datetime import datetime

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


def init_db(db_path: str):
    """Initialize database tables if they don't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Archive cursor table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_cursor (
            id INTEGER PRIMARY KEY, 
            seq INTEGER, 
            updated_at TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO archive_cursor (id, seq) VALUES (1, 0)")
    
    # Archived messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archived_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq INTEGER,
            msgid TEXT UNIQUE,
            msgtype TEXT,
            sender_id TEXT,
            room_id TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Chat files table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msgid TEXT,
            room_id TEXT,
            sender_id TEXT,
            filename TEXT,
            file_size INTEGER,
            file_uri TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def upload_to_qiniu(file_bytes: bytes, filename: str) -> str:
    """Upload file bytes to Qiniu and return the URL."""
    from qiniu import Auth, put_data
    
    access_key = os.getenv("QINIU_ACCESS_KEY")
    secret_key = os.getenv("QINIU_SECRET_KEY")
    bucket = os.getenv("QINIU_BUCKET")
    domain = os.getenv("QINIU_DOMAIN")
    
    if not all([access_key, secret_key, bucket, domain]):
        logger.error("Qiniu credentials not configured")
        return None
    
    # Generate unique key
    file_hash = hashlib.md5(file_bytes).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    key = f"archive/{timestamp}_{file_hash}_{filename}"
    
    q = Auth(access_key, secret_key)
    token = q.upload_token(bucket, key)
    
    ret, info = put_data(token, key, file_bytes)
    
    if info.status_code == 200:
        url = f"https://{domain}/{key}"
        logger.info(f"Uploaded to Qiniu: {url}")
        return url
    else:
        logger.error(f"Qiniu upload failed: {info}")
        return None


def process_file_message(sdk, msg: dict, cursor) -> bool:
    """Download file from WeCom and upload to Qiniu."""
    try:
        file_info = msg.get("file", {})
        sdkfileid = file_info.get("sdkfileid")
        filename = file_info.get("filename", "unknown")
        file_size = file_info.get("filesize", 0)
        
        if not sdkfileid:
            logger.warning(f"No sdkfileid in file message {msg.get('msgid')}")
            return False
        
        logger.info(f"Downloading file: {filename} ({file_size} bytes)")
        
        # Download file using SDK
        file_bytes = sdk.get_media_data(sdkfileid)
        if not file_bytes:
            logger.error(f"Failed to download file {sdkfileid}")
            return False
        
        logger.info(f"Downloaded {len(file_bytes)} bytes")
        
        # Upload to Qiniu
        file_uri = upload_to_qiniu(file_bytes, filename)
        if not file_uri:
            return False
        
        # Save to database using existing cursor
        cursor.execute("""
            INSERT OR REPLACE INTO chat_files 
            (msgid, room_id, sender_id, filename, file_size, file_uri, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            msg.get("msgid"),
            msg.get("roomid", ""),
            msg.get("from", ""),
            filename,
            len(file_bytes),
            file_uri
        ))
        
        logger.info(f"Saved file record: {filename} -> {file_uri}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        return False


def sync(start_seq: int):
    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("ARCHIVE_SECRET")
    priv_key_path = os.getenv("ARCHIVE_RSA_PRIVATE_KEY_PATH", "/opt/wecom-callback/keys/archive_private_key.pem")
    db_path = os.getenv("ARCHIVE_DB_PATH", os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db"))
    
    if not corp_id or not secret:
        return {"status": "error", "message": "Missing WECOM_CORP_ID or ARCHIVE_SECRET"}

    # Initialize database
    init_db(db_path)

    # Initialize SDK
    sdk = WeWorkFinanceSDK()
    if not sdk.init(corp_id, secret):
        return {"status": "error", "message": "Failed to initialize SDK"}

    # Pull messages
    chat_data = sdk.get_chat_data(start_seq, limit=100)
    if not chat_data:
        return {"status": "ok", "new_max_seq": start_seq, "processed": 0, "files": 0}

    # Load private key
    try:
        with open(priv_key_path, "rb") as f:
            priv_key = RSA.importKey(f.read())
    except Exception as e:
        return {"status": "error", "message": f"Failed to load private key: {e}"}
    
    cipher_rsa = PKCS1_v1_5.new(priv_key)
    new_max_seq = start_seq
    processed = 0
    files_processed = 0
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
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
            msg_type = decrypted_msg.get("msgtype", "unknown")
            
            # Save message to database
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO archived_messages 
                    (seq, msgid, msgtype, sender_id, room_id, content, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    msg['seq'],
                    decrypted_msg.get("msgid", msg.get("msgid")),
                    msg_type,
                    decrypted_msg.get("from", ""),
                    decrypted_msg.get("roomid", ""),
                    json.dumps(decrypted_msg, ensure_ascii=False)
                ))
            except Exception as e:
                logger.warning(f"Failed to save message: {e}")
            
            # Handle file messages
            if msg_type == "file":
                if process_file_message(sdk, decrypted_msg, cursor):
                    files_processed += 1
            
            logger.info(f"Processed msg seq={msg['seq']} type={msg_type}")
            new_max_seq = max(new_max_seq, msg['seq'])
            processed += 1
            
        except Exception as e:
            logger.error(f"Error processing msg {msg.get('seq')}: {e}")
    
    conn.commit()

    # Update cursor
    if new_max_seq > start_seq:
        cursor.execute("UPDATE archive_cursor SET seq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (new_max_seq,))
        conn.commit()
    
    conn.close()

    return {"status": "ok", "new_max_seq": new_max_seq, "processed": processed, "files": files_processed}

if __name__ == "__main__":
    start_seq = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    result = sync(start_seq)
    print(json.dumps(result))
