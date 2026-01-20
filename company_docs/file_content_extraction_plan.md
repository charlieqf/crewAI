# File Content Extraction Plan (Fast + Reliable)

## Goals
- Enable @gemini to answer "what is in this picture/pdf" by reliably accessing the file content.
- Enable /file-html to include extracted content from images and PDFs in hot and archive history.
- Keep response time fast for users by extracting once on ingest and reusing cached results.

## Non-goals
- Real-time OCR at report time.
- Full semantic search UI (only context injection for LLM).

## Current Gaps (Observed)
- File messages are routed to _handle_file_message but that handler is missing, so PDFs/docs are never stored or processed.
- Archive file saves call save_file without required args (sender_name, mime_type), so persistence likely fails.
- /file-html only includes text and file placeholders like [File: ...], no content extraction.

## High-level Design
1. Extract file content at ingest time (hot and archive flows).
2. Store extracted text in a dedicated table keyed by storage_key or file hash.
3. /file-html joins chat history to cached file text and injects it into the report prompt.
4. Backfill pipeline extracts content for existing stored files.

## Data Model
Add a new table `file_contents` (recommended over adding a large column to chat_messages).

Schema (SQLite):
- id INTEGER PRIMARY KEY
- chat_id TEXT NOT NULL
- wecom_msg_id TEXT
- storage_key TEXT
- file_hash TEXT NOT NULL
- filename TEXT
- mime_type TEXT
- size_bytes INTEGER
- page_count INTEGER
- extracted_text TEXT
- extracted_summary TEXT
- status TEXT NOT NULL (pending, extracted, partial, failed)
- error_message TEXT
- created_at TEXT
- updated_at TEXT
- extracted_at TEXT

Indexes:
- UNIQUE(file_hash)
- INDEX(chat_id, wecom_msg_id)
- INDEX(storage_key)
- INDEX(status)

Notes:
- Use file_hash for dedupe across uploads.
- Keep extracted_summary optional for large text truncation.

## Ingest Flow (Hot Bot Messages)
1. Implement `_handle_file_message` in `src/crewai_enterprise/server/aibot_callback.py`.
2. Route to `handlers/file_handler.process_file_message`.
3. After download, compute hash and enqueue extraction.
4. Save file context in chat storage with bot_type so lookups work.

Required updates:
- Ensure save_file includes sender_name and mime_type.
- Add storage_key to chat_messages for cloud file access.

## Archive Flow (Cold Sync)
1. In `src/crewai_enterprise/server/archive_callback.py`, fix save_file args.
2. After Qiniu upload, enqueue extraction (async).
3. Backfill uses the same extraction function.

## Extraction Pipeline
Priority order:
1. If PDF with embedded text -> extract with pypdf.
2. If extracted text empty -> OCR.
3. If image -> OCR.

OCR engine:
- PaddleOCR (preferred for Chinese accuracy). CPU-only mode, run async with strict timeouts.

Guardrails (CPU-only):
- Max file size (configurable, e.g. 25 MB).
- Max pages for OCR (configurable, e.g. 15-20).
- Per-file timeout (configurable, e.g. 60s).
- Global extraction concurrency limit (start at 1-2).

Output:
- extracted_text stored in `file_contents`.
- extracted_summary stored if text is long (first 10k chars + summary).
- status and error_message captured for monitoring.

## /file-html Integration
1. When /file-html is invoked, fetch history via get_merged_chat_history.
2. For file messages, resolve storage_key or hash and pull extracted_text.
3. Inject file content into archive_context with labels:
   - [File: filename]
   - Extracted text snippet (truncate at 5k chars per file).
4. If extraction missing or failed, add a note.

## Quoted File Analysis
1. Quote resolution should retrieve file context (by msg id or filename).
2. If file context exists and extracted_text cached:
   - Use cached text in the prompt for fast response.
3. If file context exists but no cached text:
   - Trigger extraction async and respond with a short "processing" hint.

## Backfill Plan (Required)
1. Scan chat_storage.db for file contexts.
2. For each file with storage_key, download and extract.
3. Deduplicate by file_hash.
4. Save to file_contents table.

Implementation idea:
- Add script `scripts/backfill_file_contents.py` with:
  - --since-date
  - --limit
  - --concurrency
  - --dry-run

## Implementation Steps
Phase 1: Data model and core extraction
- Add file_contents table + migrations.
- Implement file hash utility.
- Implement extract_text_from_pdf + OCR wrapper.
- Implement extraction job with timeouts and status tracking.

Phase 2: Ingest integration
- Implement `_handle_file_message` and call process_file_message.
- Fix archive_callback save_file args and enqueue extraction.
- Save bot_type for hot and archive file contexts.

Phase 3: /file-html integration
- Extend archive_tool to join file_contents for file placeholders.
- Update _format_chat_history to inject extracted text blocks.

Phase 4: Backfill
- Implement backfill script and run for existing files.
- Monitor extraction status and errors.

## Configuration
New env vars:
- FILE_EXTRACT_MAX_SIZE_MB=25
- FILE_EXTRACT_MAX_PAGES=15
- FILE_EXTRACT_TIMEOUT_SEC=60
- FILE_EXTRACT_CONCURRENCY=1
- OCR_ENGINE=paddle

## Telemetry and Monitoring
Logs:
- extraction start/end, duration, status, file_hash.
Metrics:
- extracted_count, failed_count, avg_duration.
Alerts:
- high failure rate or long extraction times.

## Testing Plan
Unit tests:
- PDF text extraction with embedded text.
- OCR fallback for image-only PDFs.
- File hash dedupe.
- file_contents upsert logic.

Integration tests:
- Ingest a PDF and verify extracted_text stored.
- /file-html includes extracted text in prompt.
- Archive backfill extracts and caches.

## Rollout
1. Deploy schema changes.
2. Enable extraction for new files only (feature flag).
3. Run backfill with low concurrency.
4. Monitor errors and performance.
5. Enable report integration to use cached text.

## Open Questions
- OCR compute budget (CPU-only on the same VM; enforce strict limits).
- Storage limits for extracted_text (truncate rules).
- Whether to store per-page results for better summaries.

## Technical Challenges and Critical Review

### 1. OCR Throughput and Latency (CPU-only)
*   **Challenge**: PaddleOCR on CPU will be slow for multi-page PDFs and high-frequency uploads.
*   **Mitigation**: Keep it simple: low concurrency (1), strict size/page caps, timeouts, and async extraction. Respond with a short "processing" hint and update when done (no queue position).

### 2. Database Scalability (Keep it simple)
*   **Challenge**: Storing large extracted text can bloat SQLite over time.
*   **Mitigation**: Separate `file_contents` table, truncate stored text, and avoid FTS for now. Revisit FTS only if a search feature is needed.

### 3. Context Truncation (Low-cost)
*   **Challenge**: Truncation can omit important sections in long documents.
*   **Mitigation**: Use a fixed truncation budget per file and include a short fallback note. Page-level summaries are optional future work, not required for v1.

### 4. Archive Sync Pressure (Resource Exhaustion)
*   **Challenge**: Backfill can spike CPU and impact live traffic.
*   **Mitigation**: Run backfill with low concurrency and off-peak scheduling. Throttle aggressively and allow pause/resume.

### 5. Extraction Quality for Non-Text PDFs
*   **Challenge**: `pypdf` misses scanned or complex layouts.
*   **Mitigation**: OCR fallback is the only requirement for v1. Advanced layout tools are out of scope for the low-cost path.
