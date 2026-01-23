## WeCom Archive + OCR Ops Runbook

### What We Fixed

**Archive timestamps**
- `archived_messages.created_at` already stored in Beijing time.
- `chat_files.created_at` was UTC (CURRENT_TIMESTAMP); changed to Beijing time based on message `msgtime`.
- Migrated existing `chat_files` timestamps by +8 hours.

**Bot callbacks**
- `wecom-callback` loads env from `/etc/wecom-callback/env`.
- Missing `*_BOT_TOKEN` and `*_BOT_ENCODING_AES_KEY` will break `/ai-bot/{bot}` callbacks.
- Ensure these are present for chatgpt/gemini/grok.

**OCR pipeline**
- Google Vision OCR for images; PaddleOCR for PDFs.
- OCR backfill now reads from `chat_files` LEFT JOIN `file_contents`, so all archive files are eligible.
- OCR backfill is limited to images and PDFs only.

**File HTML context injection**
- File-html outputs use a single context appender (`utils/html_context.py`) for consistent placement.
- For file output, archive context is injected into the system prompt (not user content).
- LLM is instructed to NOT embed raw context; the system appends it at the end.

**UI**
- Archive viewer files table: `文件名` auto-size, `提取内容` gets remaining width.

### Where to Look

- Archive DB: `/var/lib/wecom-callback/chat_history.db`
- OCR DB: `/var/lib/wecom-callback/chat_storage.db`
- Archive worker: `/opt/wecom-callback/scripts/archive_sync_worker.py`
- Catch-up sync: `/opt/wecom-callback/scripts/catchup_sync_by_date.py`
- OCR backfill: `/opt/wecom-callback/scripts/backfill_ocr_throttled.py`
- Archive viewer: `/opt/wecom-callback/src/crewai_enterprise/server/archive_viewer.py`
- Bot callback config: `/etc/wecom-callback/env`

### Google Vision OCR

**Credentials**
- `/opt/wecom-callback/keys/google_vision.json` (chmod 600)

**Env**
- `GOOGLE_VISION_ENABLED=true`
- `GOOGLE_APPLICATION_CREDENTIALS=/opt/wecom-callback/keys/google_vision.json`

**API**
- Ensure Vision API is enabled for project `113637336222`

### Common Issues + Fixes

**Archive page stale**
- Check archive cursor and latest timestamp.
- Clear lock and run a single sync.
  - Stale lock can remain if the sync worker is killed or crashes before cleanup.

**Bot no response**
- Look for 500s on `/ai-bot/{bot}`.
- Verify `/etc/wecom-callback/env` has `CHATGPT_BOT_TOKEN`, `CHATGPT_BOT_ENCODING_AES_KEY`, `GEMINI_BOT_TOKEN`, `GEMINI_BOT_ENCODING_AES_KEY`, `GROK_BOT_TOKEN`, `GROK_BOT_ENCODING_AES_KEY`.
- Restart `wecom-callback` after env updates.

**Duplicate archive workers**
- `scripts/backfill_loop.sh` spawns workers; stop it if running.
- Use a single manual sync when debugging.

**OCR missing for archive files**
- Files appear in `chat_files` but not `file_contents` until OCR runs.
- Backfill must be driven by `chat_files LEFT JOIN file_contents`.

**OCR timeouts**
- Use Google Vision; local OCR is disabled.
- Adjust `OCR_MAX_IMAGE_BYTES` or `OCR_TIMEOUT_SECS` as needed.
- For PDFs, use `OCR_MAX_PDF_BYTES` (separate from image limit).

**File-html context not at bottom**
- Ensure `utils/html_context.append_context_section` is used (context appended via id `raw-context-section`).
- Confirm file-html is not injecting archive context into user message content.

### Quick SQL Checks

**Archive cursor + latest**
```sql
SELECT seq, updated_at FROM archive_cursor WHERE id = 1;
SELECT MAX(created_at) FROM archived_messages;
```

**File OCR status**
```sql
SELECT status, COUNT(*) FROM file_contents WHERE mime_type LIKE 'image/%' GROUP BY status;
```

### Recommended Backfill Commands

**Catch-up messages (one-shot)**
```bash
/opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/catchup_sync_by_date.py --from-date 2026-01-20
```

**OCR backfill (since date, Google Vision)**
```bash
OCR_TIMEOUT_SECS=30 OCR_MAX_IMAGE_BYTES=1048576 OCR_SIMPLE=true \
GOOGLE_VISION_ENABLED=true GOOGLE_APPLICATION_CREDENTIALS=/opt/wecom-callback/keys/google_vision.json \
/opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/backfill_ocr_throttled.py 200 1 "2026-01-23 12:18:15"
```

### Service Restart

```bash
systemctl restart wecom-callback
systemctl is-active wecom-callback
```
