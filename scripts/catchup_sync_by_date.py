#!/usr/bin/env python3
"""
Catch up WeCom archive messages from a specified datetime.

This script pulls chat data in batches using the WeCom Finance SDK, filters
messages older than a cutoff datetime, and writes newer messages into
archived_messages (INSERT OR IGNORE). It advances the archive_cursor based
on the last seq seen in each batch to avoid getting stuck when seq wraps.

Usage:
    python catchup_sync_by_date.py --from-date 2026-01-16
    python catchup_sync_by_date.py --from-date "2026-01-16 00:00:00" --limit 100
"""
import argparse
import base64
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/opt/wecom-callback")

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from qiniu import Auth, put_data

from src.crewai_enterprise.utils.wework_finance_sdk import WeWorkFinanceSDK

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

MAX_ARCHIVE_FILE_BYTES = 5 * 1024 * 1024
DEFAULT_LOCK = "/var/lib/wecom-callback/archive_sync.lock"


def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()


def parse_cutoff(raw: str) -> datetime:
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            continue
    raise ValueError("Invalid --from-date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(lock_path: str) -> int | None:
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
            if raw.isdigit() and is_pid_alive(int(raw)):
                logger.warning("Archive sync lock held by live PID=%s", raw)
                return None
        except Exception:
            pass
        try:
            os.remove(lock_path)
        except OSError:
            logger.warning("Failed to remove stale lock: %s", lock_path)
            return None

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        return fd
    except FileExistsError:
        logger.warning("Archive sync lock already exists.")
        return None


def release_lock(lock_path: str, fd: int | None) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        os.remove(lock_path)
    except OSError:
        pass


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_cursor (
            id INTEGER PRIMARY KEY,
            seq INTEGER,
            updated_at TEXT
        )
        """
    )
    cursor.execute("INSERT OR IGNORE INTO archive_cursor (id, seq) VALUES (1, 0)")
    cursor.execute(
        """
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
        """
    )
    cursor.execute(
        """
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
        """
    )
    conn.commit()
    conn.close()


def _detect_image_extension(file_bytes: bytes) -> str:
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if file_bytes.startswith(b"GIF87a") or file_bytes.startswith(b"GIF89a"):
        return "gif"
    if file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP":
        return "webp"
    return "jpg"


def _get_content_type(ext: str) -> str:
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")


def upload_to_qiniu(file_bytes: bytes, filename: str, content_type: str | None) -> str | None:
    access_key = os.getenv("QINIU_ACCESS_KEY")
    secret_key = os.getenv("QINIU_SECRET_KEY")
    bucket = os.getenv("QINIU_BUCKET")
    domain = os.getenv("QINIU_DOMAIN")
    if not all([access_key, secret_key, bucket, domain]):
        logger.error("Qiniu credentials not configured")
        return None

    file_hash = hashlib.md5(file_bytes).hexdigest()[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    key = f"archive/{timestamp}_{file_hash}_{filename}"
    token = Auth(access_key, secret_key).upload_token(bucket, key)
    ret, info = put_data(token, key, file_bytes, mime_type=content_type or "application/octet-stream")
    if info.status_code == 200:
        return f"https://{domain}/{key}"
    logger.error("Qiniu upload failed: %s", info)
    return None


def process_file_message(sdk, msg: dict, cursor) -> bool:
    file_info = msg.get("file", {})
    sdkfileid = file_info.get("sdkfileid")
    filename = file_info.get("filename", "unknown")
    file_size = file_info.get("filesize", 0)

    if not sdkfileid:
        return False
    if file_size and file_size > MAX_ARCHIVE_FILE_BYTES:
        return False

    file_bytes = sdk.get_media_data(sdkfileid)
    if not file_bytes:
        return False

    file_uri = upload_to_qiniu(file_bytes, filename, None)
    if not file_uri:
        return False

    cursor.execute(
        """
        INSERT OR REPLACE INTO chat_files
        (msgid, room_id, sender_id, filename, file_size, file_uri, created_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            msg.get("msgid"),
            msg.get("roomid", ""),
            msg.get("from", ""),
            filename,
            len(file_bytes),
            file_uri,
        ),
    )
    return True


def process_image_message(sdk, msg: dict, cursor) -> bool:
    image_info = msg.get("image", {})
    sdkfileid = image_info.get("sdkfileid")
    msgid = msg.get("msgid") or f"unnamed_{int(time.time())}"
    file_size = image_info.get("filesize", 0)

    if not sdkfileid:
        return False
    if file_size and file_size > MAX_ARCHIVE_FILE_BYTES:
        return False

    image_bytes = sdk.get_media_data(sdkfileid)
    if not image_bytes:
        return False

    ext = _detect_image_extension(image_bytes)
    content_type = _get_content_type(ext)
    filename = f"{msgid}.{ext}"
    file_uri = upload_to_qiniu(image_bytes, filename, content_type)
    if not file_uri:
        return False

    cursor.execute(
        """
        INSERT OR REPLACE INTO chat_files
        (msgid, room_id, sender_id, filename, file_size, file_uri, created_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            msgid,
            msg.get("roomid", ""),
            msg.get("from", ""),
            filename,
            len(image_bytes),
            file_uri,
        ),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS (UTC+8)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--start-seq", type=int, default=None)
    parser.add_argument("--skip-files", action="store_true")
    parser.add_argument("--env-path", default="/etc/wecom-callback/env")
    args = parser.parse_args()

    load_env(args.env_path)

    corp_id = os.getenv("WECOM_CORP_ID")
    secret = os.getenv("ARCHIVE_SECRET")
    priv_key_path = os.getenv("ARCHIVE_RSA_PRIVATE_KEY_PATH", "/opt/wecom-callback/keys/archive_private_key.pem")
    db_path = os.getenv("ARCHIVE_DB_PATH") or os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
    lock_path = os.getenv("ARCHIVE_SYNC_LOCK", DEFAULT_LOCK)

    if not corp_id or not secret:
        logger.error("Missing WECOM_CORP_ID or ARCHIVE_SECRET")
        return 1

    cutoff = parse_cutoff(args.from_date)
    logger.info("Using cutoff datetime: %s", cutoff.strftime("%Y-%m-%d %H:%M:%S"))

    init_db(db_path)

    lock_fd = acquire_lock(lock_path)
    if lock_fd is None:
        logger.error("Unable to acquire archive sync lock.")
        return 1

    try:
        sdk = WeWorkFinanceSDK()
        if not sdk.init(corp_id, secret):
            logger.error("Failed to initialize SDK")
            return 1

        try:
            with open(priv_key_path, "rb") as handle:
                priv_key = RSA.importKey(handle.read())
        except Exception as exc:
            logger.error("Failed to load private key: %s", exc)
            return 1

        cipher_rsa = PKCS1_v1_5.new(priv_key)
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()

        if args.start_seq is not None:
            current_seq = args.start_seq
        else:
            row = cursor.execute("SELECT seq FROM archive_cursor WHERE id = 1").fetchone()
            current_seq = row[0] if row else 0

        processed = 0
        skipped = 0
        files_processed = 0
        no_progress_rounds = 0

        while True:
            chat_data = sdk.get_chat_data(current_seq, limit=args.limit)
            if chat_data is None:
                logger.error("SDK get_chat_data failed")
                break
            if not chat_data:
                logger.info("No more messages returned.")
                break

            last_seq = current_seq
            for msg in chat_data:
                msg_seq = msg.get("seq")
                if isinstance(msg_seq, int):
                    last_seq = msg_seq

                try:
                    encrypted_key = base64.b64decode(msg.get("encrypt_random_key", ""))
                    if not encrypted_key:
                        skipped += 1
                        continue
                    random_key_bytes = cipher_rsa.decrypt(encrypted_key, None)
                    if not random_key_bytes:
                        skipped += 1
                        continue
                    random_key = random_key_bytes.decode("utf-8")
                    decrypted_json = sdk.decrypt_data(random_key, msg.get("encrypt_chat_msg", ""))
                    if not decrypted_json:
                        skipped += 1
                        continue
                    decrypted_msg = json.loads(decrypted_json)
                except Exception:
                    skipped += 1
                    continue

                msg_time_ms = decrypted_msg.get("msgtime", 0)
                if msg_time_ms:
                    dt_utc = datetime.fromtimestamp(msg_time_ms / 1000.0, tz=timezone.utc)
                    dt_beijing = dt_utc.astimezone(timezone(timedelta(hours=8)))
                else:
                    dt_beijing = datetime.now(timezone(timedelta(hours=8)))

                if dt_beijing < cutoff:
                    skipped += 1
                    continue

                msg_type = decrypted_msg.get("msgtype", "unknown")
                created_at_str = dt_beijing.strftime("%Y-%m-%d %H:%M:%S")

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
                processed += 1

                if not args.skip_files:
                    if msg_type == "file" and process_file_message(sdk, decrypted_msg, cursor):
                        files_processed += 1
                    elif msg_type == "image" and process_image_message(sdk, decrypted_msg, cursor):
                        files_processed += 1

            if last_seq == current_seq:
                no_progress_rounds += 1
            else:
                no_progress_rounds = 0
                cursor.execute(
                    "UPDATE archive_cursor SET seq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                    (last_seq,),
                )
                conn.commit()
                current_seq = last_seq

            logger.info(
                "batch done: cursor=%s processed=%s skipped=%s files=%s",
                current_seq,
                processed,
                skipped,
                files_processed,
            )

            if no_progress_rounds >= 2:
                logger.warning("No cursor progress for 2 rounds; stopping.")
                break

        conn.commit()
        conn.close()

        logger.info(
            "done: processed=%s skipped=%s files=%s cursor=%s",
            processed,
            skipped,
            files_processed,
            current_seq,
        )
        return 0
    finally:
        release_lock(lock_path, lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
