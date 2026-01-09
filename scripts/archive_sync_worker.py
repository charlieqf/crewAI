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
import time
from datetime import datetime, timedelta, timezone

# Add project to path
sys.path.insert(0, "/opt/wecom-callback")

MAX_ARCHIVE_FILE_BYTES = 5 * 1024 * 1024
ARCHIVE_SYNC_LOCK = os.getenv("ARCHIVE_SYNC_LOCK", "/var/lib/wecom-callback/archive_sync.lock")

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
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    
    # Enable WAL mode for better concurrency
    cursor.execute("PRAGMA journal_mode=WAL")
    
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


def _detect_image_extension(file_bytes: bytes) -> str:
    """Detect image extension from magic bytes."""
    if file_bytes.startswith(b'\xff\xd8\xff'):
        return "jpg"
    elif file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        return "png"
    elif file_bytes.startswith(b'GIF87a') or file_bytes.startswith(b'GIF89a'):
        return "gif"
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBP':
        return "webp"
    return "jpg"  # Default fallback

def _get_content_type(ext: str) -> str:
    """Get MIME type from extension."""
    types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp"
    }
    return types.get(ext, "application/octet-stream")

def upload_to_qiniu(file_bytes: bytes, filename: str, content_type: str = None) -> str:
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
    
    # Pass params to put_data if content_type is provided
    # The put_data signature: put_data(up_token, key, data, params=None, mime_type='application/octet-stream', check_crc=False, progress_handler=None, etag=None)
    ret, info = put_data(token, key, file_bytes, mime_type=content_type or 'application/octet-stream')
    
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

        if file_size and file_size > MAX_ARCHIVE_FILE_BYTES:
            logger.warning(
                f"Skipping large file {filename} ({file_size} bytes) > {MAX_ARCHIVE_FILE_BYTES} bytes"
            )
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


def process_image_message(sdk, msg: dict, cursor) -> bool:
    """Download image from WeCom and upload to Qiniu."""
    try:
        image_info = msg.get("image", {})
        sdkfileid = image_info.get("sdkfileid")
        # Robustly handle missing msgid
        msgid = msg.get("msgid") or f"unnamed_{int(time.time())}"
        file_size = image_info.get("filesize", 0)

        if not sdkfileid:
            logger.warning(f"No sdkfileid in image message {msgid}")
            return False

        # [FIX] Apply High finding: check file size against limit
        if file_size and file_size > MAX_ARCHIVE_FILE_BYTES:
            logger.warning(
                f"Skipping large image ({file_size} bytes) > {MAX_ARCHIVE_FILE_BYTES} bytes"
            )
            return False

        logger.info(f"Downloading image: {msgid} ({file_size} bytes)")
        
        # Download image using SDK
        image_bytes = sdk.get_media_data(sdkfileid)
        if not image_bytes:
            logger.error(f"Failed to download image {sdkfileid}")
            return False
        
        # Detect extension and content type
        ext = _detect_image_extension(image_bytes)
        content_type = _get_content_type(ext)
        filename = f"{msgid}.{ext}"
        
        logger.info(f"Downloaded {len(image_bytes)} bytes, type={content_type}")
        
        # Upload to Qiniu
        file_uri = upload_to_qiniu(image_bytes, filename, content_type=content_type)
        if not file_uri:
            return False
        
        # Save to database using existing cursor
        cursor.execute("""
            INSERT OR REPLACE INTO chat_files 
            (msgid, room_id, sender_id, filename, file_size, file_uri, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            msgid,
            msg.get("roomid", ""),
            msg.get("from", ""),
            filename,
            len(image_bytes),
            file_uri
        ))
        
        logger.info(f"Saved image record: {filename} -> {file_uri}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return False


def sync(start_seq: int):
    lock_fd = None
    try:
        try:
            lock_fd = os.open(ARCHIVE_SYNC_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(lock_fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError:
            logger.warning("Archive sync already running; skipping new run.")
            return {"status": "ok", "new_max_seq": start_seq, "processed": 0, "files": 0}
        except Exception as e:
            return {"status": "error", "message": f"Failed to acquire sync lock: {e}"}

        corp_id = os.getenv("WECOM_CORP_ID")
        secret = os.getenv("ARCHIVE_SECRET")
        priv_key_path = os.getenv(
            "ARCHIVE_RSA_PRIVATE_KEY_PATH",
            "/opt/wecom-callback/keys/archive_private_key.pem",
        )
        db_path = os.getenv("ARCHIVE_DB_PATH")
        if not db_path:
            db_path = os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
            logger.warning(
                f"ARCHIVE_DB_PATH not set, falling back to {db_path}. Contention may occur."
            )

        if not corp_id or not secret:
            return {"status": "error", "message": "Missing WECOM_CORP_ID or ARCHIVE_SECRET"}

        # Initialize database
        init_db(db_path)

        # Initialize SDK
        sdk = WeWorkFinanceSDK()
        if not sdk.init(corp_id, secret):
            return {"status": "error", "message": "Failed to initialize SDK"}

        # Pull messages
        chat_data = sdk.get_chat_data(start_seq, limit=500)
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

        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()

        for msg in chat_data:
            msg_seq = msg.get("seq", 0)
            try:
                # Update sequence immediately to ensure we advance even on failure
                # (Cursor is committed at the end of the batch)
                new_max_seq = max(new_max_seq, msg_seq)

                # RSA Decrypt
                encrypted_key = base64.b64decode(msg.get("encrypt_random_key", ""))
                if not encrypted_key:
                    logger.warning(f"No encrypted_key for msg seq={msg_seq}")
                    continue

                random_key_bytes = cipher_rsa.decrypt(encrypted_key, None)
                if not random_key_bytes:
                    logger.warning(f"RSA decryption failed for msg seq={msg_seq}")
                    continue
                random_key = random_key_bytes.decode("utf-8")

                # SDK Decrypt
                decrypted_json = sdk.decrypt_data(random_key, msg.get("encrypt_chat_msg", ""))
                if not decrypted_json:
                    logger.warning(f"SDK decryption failed for msg seq={msg_seq}")
                    continue

                decrypted_msg = json.loads(decrypted_json)
                msg_type = decrypted_msg.get("msgtype", "unknown")

                # Save message to database
                try:
                    # Convert msgtime (milliseconds) to UTC+8 string
                    msg_time_ms = decrypted_msg.get("msgtime", 0)
                    if msg_time_ms:
                        # WeCom msgtime is in milliseconds
                        dt_utc = datetime.fromtimestamp(msg_time_ms / 1000.0, tz=timezone.utc)
                        # Offset to Beijing Time (UTC+8)
                        dt_beijing = dt_utc.astimezone(timezone(timedelta(hours=8)))
                        created_at_str = dt_beijing.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        created_at_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO archived_messages 
                        (seq, msgid, msgtype, sender_id, room_id, content, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            msg_seq,
                            decrypted_msg.get("msgid", msg.get("msgid")),
                            msg_type,
                            decrypted_msg.get("from", ""),
                            decrypted_msg.get("roomid", ""),
                            json.dumps(decrypted_msg, ensure_ascii=False),
                            created_at_str,
                        ),
                    )
                except Exception as e:
                    logger.warning(f"Failed to save message seq={msg_seq}: {e}")

                if msg_type == "file":
                    if process_file_message(sdk, decrypted_msg, cursor):
                        files_processed += 1
                elif msg_type == "image":
                    if process_image_message(sdk, decrypted_msg, cursor):
                        files_processed += 1

                logger.info(f"Processed msg seq={msg_seq} type={msg_type}")
                processed += 1

            except Exception as e:
                logger.error(f"Error processing msg {msg_seq}: {e}")

        conn.commit()

        # Update cursor
        if new_max_seq > start_seq:
            cursor.execute(
                "UPDATE archive_cursor SET seq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (new_max_seq,),
            )
            conn.commit()

        conn.close()

        return {
            "status": "ok",
            "new_max_seq": new_max_seq,
            "processed": processed,
            "files": files_processed,
        }
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
            try:
                os.remove(ARCHIVE_SYNC_LOCK)
            except OSError:
                pass

if __name__ == "__main__":
    start_seq = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    result = sync(start_seq)
    print(json.dumps(result))
