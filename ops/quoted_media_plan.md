# Quoted Image/PDF Question Handling

## Analysis
Goal: When a user explicitly quotes an image or PDF, prefer sending the actual
file bytes to the LLM for best accuracy. If bytes are not available yet,
fallback to OCR text. If neither bytes nor OCR are available, trigger a
one-shot archive sync and ask the user to retry.

Key constraints from current system:
- Quote payload provides quoted_msg_id and possibly a quoted filename.
- Archive worker stores chat_files and file_contents (OCR), but does not store
  image file context in chat_messages for images.
- Vision/file LLM input exists (e.g., Gemini chat_with_file) and requires bytes
  or a URI.
- Archive sync runs in batches of 100 and OCR can lag.

## Scenarios
1) Quoted image/PDF is already in context storage
   - get_active_file(chat_id, wecom_msg_id=quoted_msg_id) returns file context.
   - Use file bytes/URI with chat_with_file.

2) Quoted image/PDF is archived and OCR exists
   - Resolve via chat_files + file_contents.
   - If file_uri/storage_key exists, download bytes and use chat_with_file.
   - If bytes unavailable, use OCR text for response.

3) Quoted image/PDF is archived but OCR pending or failed
   - If file_uri exists, still use bytes.
   - If no bytes, reply that OCR is pending and ask user to retry.

4) Quoted image/PDF not archived yet
   - No chat_files or file_contents record.
   - Trigger one-shot sync in background, reply with retry guidance.

5) Quote is not a file/image
   - Normal text flow; no special handling.

6) Provider does not support file inputs
   - Use OCR text if available; otherwise respond normally.

7) File too large or download fails
   - If bytes too large, use OCR text if available; otherwise ask to retry.

## Implementation Plan

1) Add a quoted media resolver utility
   - File: src/crewai_enterprise/server/handlers/aibot/quoted_media.py
   - Inputs: chat_id, quoted_msg_id, quoted_filename, bot_type
   - Outputs: file_ctx (uri, storage_key, mime, filename), file_bytes (optional),
     ocr_text (optional), status (found_bytes, found_ocr, pending, not_found).
   - Resolution order:
     a) Context store: get_active_file(chat_id, wecom_msg_id=quoted_msg_id)
     b) Archive DB: chat_files by msgid; fallback to filename if provided
     c) OCR: file_contents by wecom_msg_id

2) Add a one-shot sync trigger utility
   - File: src/crewai_enterprise/server/handlers/aibot/sync_trigger.py
   - Behavior:
     - Check archive_sync.lock
     - If stale PID or lock older than threshold, remove
     - Start archive_sync_worker.py 0 with nohup
     - Rate-limit triggers (e.g., once per 2 minutes)

3) Wire into LLM flow (llm_orchestrator)
   - In _call_llm_async, before building messages:
     a) If quoted_msg_id exists and looks like file/image:
        - Resolve quoted media
        - If bytes and provider supports file inputs: use chat_with_file
        - Else if OCR text: prepend OCR snippet to user message
        - Else trigger one-shot sync and reply with retry guidance
     b) Otherwise use normal flow

4) Update quote handling in aibot_callback
   - Ensure quoted_filename is passed to _call_llm_async (already extracted)

5) Update runbook
   - Document quote flow: bytes -> OCR -> sync -> retry
   - Document sync trigger and lock cleanup
   - Document env and size limits

## Expected Behavior
- Best case: quoted image/PDF -> bytes -> vision/file model answer
- If not archived: trigger sync and ask user to retry in 1-2 minutes
- If OCR exists but bytes missing: answer using OCR text
- If provider lacks file support: OCR fallback
