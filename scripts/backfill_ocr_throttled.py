import os
import sys
import sqlite3
import logging
import time
import requests
import io
import multiprocessing
import traceback

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add app to path
sys.path.insert(0, '/opt/wecom-callback')

# Force enable OCR for this script
os.environ['DISABLE_OCR'] = 'false'
# Limit threading to save memory/CPU
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_allocator_strategy'] = 'naive_best_fit'
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_use_gpu'] = '0'
os.environ['OCR_SIMPLE'] = 'true'
os.environ.setdefault('GOOGLE_VISION_ENABLED', 'true')
os.environ.setdefault('GOOGLE_APPLICATION_CREDENTIALS', '/opt/wecom-callback/keys/google_vision.json')

try:
    from src.crewai_enterprise.utils.file_extractor import extract_text_from_file
    from src.crewai_enterprise.utils.file_extractor import compute_file_hash
    from src.crewai_enterprise.utils.file_content_store import FileContentStore
except ImportError as e:
    logger.error(f"Failed to import extractor: {e}")
    sys.exit(1)

DB_PATH = "/var/lib/wecom-callback/chat_storage.db"
OCR_TIMEOUT_SECS = int(os.getenv("OCR_TIMEOUT_SECS", "60"))
MAX_IMAGE_BYTES = int(os.getenv("OCR_MAX_IMAGE_BYTES", "262144"))
MAX_PDF_BYTES = int(os.getenv("OCR_MAX_PDF_BYTES", "5242880"))
ALLOWED_MIME_PREFIXES = ("image/",)
ALLOWED_MIME_TYPES = ("application/pdf",)


def _get_mime_type(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    image_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    for ext, mime in image_types.items():
        if name.endswith(ext):
            return mime
    return "application/octet-stream"


def _is_allowed_mime(mime_type: str) -> bool:
    if not mime_type:
        return False
    if mime_type in ALLOWED_MIME_TYPES:
        return True
    return any(mime_type.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES)


def _extract_worker(file_bytes: bytes, mime_type: str, queue) -> None:
    try:
        result = extract_text_from_file(file_bytes, mime_type)
        queue.put(("ok", result.text, result.status, result.error))
    except Exception:
        queue.put(("err", "", "failed", traceback.format_exc()))


def _extract_with_timeout(file_bytes: bytes, mime_type: str, timeout_secs: int):
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    proc = ctx.Process(target=_extract_worker, args=(file_bytes, mime_type, queue))
    proc.start()
    proc.join(timeout_secs)
    if proc.is_alive():
        proc.terminate()
        proc.join()
        return "", "failed", f"OCR timeout after {timeout_secs}s"
    try:
        status, text, result_status, error = queue.get_nowait()
    except Exception:
        return "", "failed", "OCR failed: no result"
    if status != "ok":
        return "", "failed", error or "OCR failed"
    return text or "", result_status or "failed", error

def backfill(limit=1000, cooldown=10, since_date=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Enable WAL for concurrency
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("ATTACH DATABASE '/var/lib/wecom-callback/chat_history.db' AS history_db")
    
    query = """
        SELECT
            f.msgid,
            f.room_id,
            f.sender_id,
            f.filename,
            f.file_size,
            f.file_uri,
            COALESCE(s.file_hash, '') AS file_hash,
            COALESCE(s.status, 'pending') AS status,
            COALESCE(s.mime_type, '') AS mime_type,
            COALESCE(s.storage_key, '') AS storage_key
        FROM history_db.chat_files f
        LEFT JOIN file_contents s
            ON f.msgid = s.wecom_msg_id
        WHERE f.file_uri IS NOT NULL
          AND (s.status IS NULL OR s.status IN ('failed', 'pending'))
          AND (
                s.mime_type LIKE 'image/%'
             OR s.mime_type = 'application/pdf'
             OR s.mime_type = 'application/octet-stream'
             OR (
                    (s.mime_type IS NULL OR s.mime_type = '')
                AND (
                       lower(f.filename) LIKE '%.pdf'
                    OR lower(f.filename) LIKE '%.png'
                    OR lower(f.filename) LIKE '%.jpg'
                    OR lower(f.filename) LIKE '%.jpeg'
                    OR lower(f.filename) LIKE '%.gif'
                    OR lower(f.filename) LIKE '%.bmp'
                    OR lower(f.filename) LIKE '%.webp'
                )
             )
          )
    """
    params = []
    if since_date:
        query += " AND f.created_at >= ?"
        params.append(since_date)
    query += " ORDER BY f.created_at ASC"
    
    query += " LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    
    rows = cursor.fetchall()
    logger.info(f"Found {len(rows)} files to process since {since_date}")
    
    total_processed = 0
    for msgid, room_id, sender_id, filename, file_size, file_uri, file_hash, status, mime_type, storage_key in rows:
        storage_key = storage_key or file_uri
        if not mime_type:
            mime_type = _get_mime_type(filename or "")
        if mime_type == "application/octet-stream":
            mime_type = _get_mime_type(filename or "")
        if not _is_allowed_mime(mime_type):
            logger.info(f"Skipping non-image/pdf file {msgid} (mime={mime_type})")
            continue
        if file_size:
            max_bytes = MAX_PDF_BYTES if mime_type == "application/pdf" else MAX_IMAGE_BYTES
            if file_size > max_bytes:
                logger.info(
                    f"Skipping {msgid}: {file_size} bytes > {max_bytes} (mime={mime_type})"
                )
                continue
        logger.info(f"[{total_processed+1}/{len(rows)}] Processing {msgid} ({mime_type})")
        
        try:
            # Download from Qiniu
            url = storage_key
            if not url.startswith('http'):
                domain = os.getenv("QINIU_DOMAIN", "wecomfile.medmeeting.com")
                url = f"https://{domain}/{storage_key}"
            
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Failed to download {url}: {resp.status_code}")
                continue
            
            content = resp.content
            max_bytes = MAX_PDF_BYTES if mime_type == "application/pdf" else MAX_IMAGE_BYTES
            if content and len(content) > max_bytes:
                logger.info(
                    f"Skipping {msgid}: {len(content)} bytes > {max_bytes} (mime={mime_type})"
                )
                continue
            
            # Extract
            text, status, error = _extract_with_timeout(content, mime_type, OCR_TIMEOUT_SECS)
            
            if not file_hash:
                file_hash = compute_file_hash(content)
            store = FileContentStore(db_path=DB_PATH)
            store.upsert_pending(
                file_hash=file_hash,
                chat_id=room_id,
                wecom_msg_id=msgid,
                storage_key=storage_key,
                filename=filename,
                mime_type=mime_type,
                size_bytes=len(content),
            )

            # Update DB
            cursor.execute("""
                UPDATE file_contents 
                SET extracted_text = ?, 
                    status = ?, 
                    error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE file_hash = ?
            """, (text, status, error, file_hash))
            conn.commit()
            
            logger.info(f"Done: status={status}, text_len={len(text)}")
            total_processed += 1
            
            if cooldown > 0:
                logger.info(f"Cooling down for {cooldown}s...")
                time.sleep(cooldown)
                
        except Exception as e:
            logger.error(f"Unexpected error processing {file_hash}: {e}")
            continue

    conn.close()
    logger.info(f"Finished. Processed {total_processed} files.")

if __name__ == "__main__":
    # Final check on environment before starting
    os.environ['DISABLE_OCR'] = 'false'
    
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    delay = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    since = sys.argv[3] if len(sys.argv) > 3 else "2026-01-20"
    
    logger.info(f"Starting long-run backfill: count={count}, delay={delay}, since={since}")
    backfill(limit=count, cooldown=delay, since_date=since)
