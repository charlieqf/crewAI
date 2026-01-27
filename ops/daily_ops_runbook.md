## Daily Ops Runbook (WeCom Archive + OCR)

Goal: confirm services are healthy, archives are up to date, and image/PDF extraction is current. If not, apply safe fixes. All commands are PowerShell-safe and avoid quoting traps by using a bash heredoc with SQL files.

### Prereqs
- SSH key at `$env:USERPROFILE\.ssh\kamatera`
- Target host: `104.238.213.119`

### 1) Quick Health Check (service + workers)

```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "systemctl is-active wecom-callback"
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "ps aux | grep -E 'archive_sync_worker.py|backfill_ocr_throttled.py' | grep -v grep || true"
```

Expected:
- `wecom-callback` is `active`
- No archive worker is fine (it’s on schedule), but OCR backfill may be running during catch-up.

### 2) Archive Freshness (cursor vs latest message time)

Use the temp-SQL-file pattern to avoid PowerShell + heredoc CRLF issues:

```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 'bash -s' <<'EOF'
set -e

echo "archive_cursor:"
cat <<'SQL' > /tmp/query.sql
SELECT seq, updated_at FROM archive_cursor WHERE id = 1;
SQL
sqlite3 /var/lib/wecom-callback/chat_history.db < /tmp/query.sql

echo "latest_archived_created_at:"
cat <<'SQL' > /tmp/query.sql
SELECT MAX(created_at) FROM archived_messages;
SQL
sqlite3 /var/lib/wecom-callback/chat_history.db < /tmp/query.sql

rm -f /tmp/query.sql
EOF
```

Interpretation:
- The cursor `updated_at` should be close to the latest `created_at`.
- A consistent 8‑hour offset is acceptable (Beijing vs UTC); larger gaps indicate stale sync.

If stale:
1) Check lock + PID
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 'if [ -f /var/lib/wecom-callback/archive_sync.lock ]; then cat /var/lib/wecom-callback/archive_sync.lock; ps -p $(cat /var/lib/wecom-callback/archive_sync.lock) -o pid,cmd; else echo "no lock"; fi'
```
2) Clear stale lock and run one-shot sync:
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 'bash -s' <<'EOF'
set -e
if [ -f /var/lib/wecom-callback/archive_sync.lock ]; then
  pid=$(cat /var/lib/wecom-callback/archive_sync.lock || true)
  if [ -n "$pid" ] && ! ps -p "$pid" >/dev/null 2>&1; then
    rm -f /var/lib/wecom-callback/archive_sync.lock
  fi
fi
/opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/archive_sync_worker.py 0
EOF
```

Re-check Step 2.

### 3) OCR Freshness (images + PDFs)

Check counts only for image/PDF:

```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 'bash -s' <<'EOF'
set -e
echo "ocr_status_counts_images_pdfs:"
cat <<'SQL' > /tmp/query.sql
SELECT mime_type, status, COUNT(*)
FROM file_contents
WHERE mime_type LIKE 'image/%' OR mime_type = 'application/pdf'
GROUP BY mime_type, status
ORDER BY mime_type, status;
SQL
sqlite3 /var/lib/wecom-callback/chat_storage.db < /tmp/query.sql
rm -f /tmp/query.sql
EOF
```

Interpretation:
- `pending` should trend toward 0.
- Some `failed` for non-image/pdf is expected; for images/PDFs, investigate if failures spike.

If OCR is behind or pending is high:
Run a backfill from yesterday (Google Vision for images, PaddleOCR for PDFs):

```powershell
$fromDate = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd 00:00:00')
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "nohup env OCR_TIMEOUT_SECS=30 OCR_MAX_IMAGE_BYTES=1048576 OCR_SIMPLE=true GOOGLE_VISION_ENABLED=true GOOGLE_APPLICATION_CREDENTIALS=/opt/wecom-callback/keys/google_vision.json /opt/wecom-callback/venv/bin/python /opt/wecom-callback/scripts/backfill_ocr_throttled.py 200 1 '$fromDate' >/var/log/wecom-callback/ocr_backfill.log 2>&1 &"
```

If the command returns no output for a while, it may still be running. Verify:
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 "ps aux | grep -E 'backfill_ocr_throttled.py' | grep -v grep || true"
```

Optional: recent OCR failures (images/PDFs only):
```powershell
ssh -i $env:USERPROFILE\.ssh\kamatera root@104.238.213.119 'bash -s' <<'EOF'
set -e
echo "ocr_recent_failures_images_pdfs:"
cat <<'SQL' > /tmp/query.sql
SELECT wecom_msg_id, filename, mime_type, status, error_message, updated_at
FROM file_contents
WHERE status = 'failed'
  AND (mime_type LIKE 'image/%' OR mime_type = 'application/pdf')
ORDER BY updated_at DESC
LIMIT 20;
SQL
sqlite3 /var/lib/wecom-callback/chat_storage.db < /tmp/query.sql
rm -f /tmp/query.sql
EOF
```

### 4) Summary / Decision
- If service is active, cursor is current, and OCR pending is low, you’re done.
- If archive cursor lags: run one-shot sync.
- If OCR pending is high: run backfill (and monitor).

### 5) Common Mistakes to Avoid
- Do not use PowerShell here-strings piped into `bash -s` for SQL; CRLF can break heredocs.
- Use the temp SQL file pattern (`/tmp/query.sql`) to avoid quoting/CRLF issues.
- Avoid inline `sqlite3 "SELECT ..."` in PowerShell; `(` and `*` often get misparsed.
