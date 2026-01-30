# OpenCode Debug Scripts

Quick, copy/paste-safe helpers to avoid PowerShell vs bash quoting issues.

## PowerShell (run on Windows)
- `oc-log-latest.ps1` : print latest OpenCode log path
- `oc-log-tail.ps1` : tail latest OpenCode log
- `oc-wecom-log.ps1` : tail wecom-callback logs
- `oc-session-status.ps1` : dump session status
- `oc-session-messages.ps1` : dump messages for a session
- `oc-session-summary.ps1` : summarize last user + assistant replies for a session
- `oc-storage-session-assistant.ps1` : list assistant messages + parts from OpenCode storage
- `oc-diag.ps1` : one-shot diagnostics (logs + status + latest session)

## Bash (run on the server)
- `oc-log-latest.sh`
- `oc-log-tail.sh`
- `oc-session-status.sh`
- `oc-session-messages.sh`
- `oc-session-summary.sh`
- `oc-storage-session-assistant.sh`
- `oc-diag.sh`

## Python (run anywhere with network access)
- `oc_session_dump.py` : fetch session status/messages via HTTP

## Quick examples

PowerShell:
```powershell
.\scripts\opencode_debug\oc-log-tail.ps1
.\scripts\opencode_debug\oc-wecom-log.ps1 -Minutes 15
.\scripts\opencode_debug\oc-session-messages.ps1 -SessionId ses_XXXX
.\scripts\opencode_debug\oc-session-summary.ps1 -SessionId ses_XXXX
.\scripts\opencode_debug\oc-storage-session-assistant.ps1 -SessionId ses_XXXX
.\scripts\opencode_debug\oc-diag.ps1 -Minutes 15
```

Bash (on server):
```bash
./scripts/opencode_debug/oc-log-tail.sh
./scripts/opencode_debug/oc-session-messages.sh ses_XXXX
./scripts/opencode_debug/oc-session-summary.sh ses_XXXX
./scripts/opencode_debug/oc-storage-session-assistant.sh ses_XXXX
./scripts/opencode_debug/oc-diag.sh 15 200 10
```

Python:
```bash
python3 scripts/opencode_debug/oc_session_dump.py --session ses_XXXX
```

## Common errors (and what they mean)

- `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`
  - The HTTP response body was empty or not JSON (often a timeout or upstream error).
  - Re-run with `oc-log-tail` and `oc-wecom-log` to confirm upstream status.
