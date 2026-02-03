---
name: wecom-daily-ops
description: Daily WeCom archive/OCR health checks, catch-up workflows, and worker status verification on the Kamatera host. Use when asked to check WeCom messages/files/OCR freshness, archive sync status, or run catch-up/backfill from a specific date.
---

# WeCom Daily Ops

## Workflow

1) Read `ops/daily_ops_runbook.md` for the canonical steps.
2) Run checks in this order: service status, workers, archive freshness, OCR freshness.
3) If stale or behind, run catch-up from the requested date, then re-check.
4) Report cursor time vs latest archive created_at explicitly.

## PowerShell-safe command pattern

Prefer running SSH from bash with the Windows key path to avoid PowerShell parsing issues:

```bash
ssh -i "/c/Users/rdpuser/.ssh/kamatera" root@104.238.213.119 "<remote command>"
```

Use `pgrep -af` for worker checks instead of `ps | grep` to avoid quoting and pipe issues.

## Required checks

- Service: `systemctl is-active wecom-callback`
- Workers: `pgrep -af 'archive_sync_worker.py|backfill_ocr_throttled.py'`
- Archive cursor + latest archived created_at
- OCR counts for images/PDFs

## Catch-up actions

- Archive: clear stale lock at `/opt/wecom-callback/archive_sync.lock` if needed, source `/etc/wecom-callback/env`, then run one-shot `archive_sync_worker.py 0`.
- OCR: run `backfill_ocr_throttled.py` with the requested start date; verify the log and process. Keep a single backfill process.

## Reporting

- Report whether `archive_sync_worker.py` and `backfill_ocr_throttled.py` are running.
- Include cursor seq/updated_at and latest archived created_at.
- Include OCR counts by mime_type/status.

## OCR dependency checks

- Ensure `/opt/wecom-callback/venv` has `google-cloud-vision` installed.
- Ensure `/opt/wecom-callback/keys/google_vision.json` exists and is readable.

## Reporting

- Report timestamps for cursor and latest archive; note 8-hour offset acceptable.
- Report OCR counts for pending/failed/extracted by mime type.
- State whether workers are running and whether catch-up started.
