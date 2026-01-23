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

try:
    from src.crewai_enterprise.utils.file_extractor import extract_text_from_file
except ImportError as e:
    logger.error(f"Failed to import extractor: {e}")
    sys.exit(1)

DB_PATH = "/var/lib/wecom-callback/chat_storage.db"
OCR_TIMEOUT_SECS = int(os.getenv("OCR_TIMEOUT_SECS", "60"))


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
    
    query = """
        SELECT file_hash, storage_key, mime_type 
        FROM file_contents 
        WHERE (status = 'failed' OR status = 'pending')
        AND storage_key IS NOT NULL
        AND (mime_type LIKE 'image/%' OR mime_type = 'application/pdf')
    """
    params = []
    if since_date:
        query += " AND created_at >= ?"
        params.append(since_date)
    
    query += " LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    
    rows = cursor.fetchall()
    logger.info(f"Found {len(rows)} files to process since {since_date}")
    
    total_processed = 0
    for file_hash, storage_key, mime_type in rows:
        logger.info(f"[{total_processed+1}/{len(rows)}] Processing {file_hash} ({mime_type})")
        
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
            
            # Extract
            text, status, error = _extract_with_timeout(content, mime_type, OCR_TIMEOUT_SECS)
            
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
