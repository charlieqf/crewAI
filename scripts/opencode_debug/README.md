# OpenCode Debug Scripts

Quick, copy/paste-safe helpers to avoid PowerShell vs bash quoting issues.

## PowerShell (run on Windows)
- `oc-log-latest.ps1` : print latest OpenCode log path
- `oc-log-tail.ps1` : tail latest OpenCode log
- `oc-wecom-log.ps1` : tail wecom-callback logs
- `oc-session-status.ps1` : dump session status
- `oc-session-messages.ps1` : dump messages for a session
- `oc-diag.ps1` : one-shot diagnostics (logs + status + latest session)

## Bash (run on the server)
- `oc-log-latest.sh`
- `oc-log-tail.sh`
- `oc-session-status.sh`
- `oc-session-messages.sh`
- `oc-diag.sh`

## Python (run anywhere with network access)
- `oc_session_dump.py` : fetch session status/messages via HTTP

## Quick examples

PowerShell:
```powershell
.\scripts\opencode_debug\oc-log-tail.ps1
.\scripts\opencode_debug\oc-wecom-log.ps1 -Minutes 15
.\scripts\opencode_debug\oc-session-messages.ps1 -SessionId ses_XXXX
.\scripts\opencode_debug\oc-diag.ps1 -Minutes 15
```

Bash (on server):
```bash
./scripts/opencode_debug/oc-log-tail.sh
./scripts/opencode_debug/oc-session-messages.sh ses_XXXX
./scripts/opencode_debug/oc-diag.sh 15 200 10
```

Python:
```bash
python3 scripts/opencode_debug/oc_session_dump.py --session ses_XXXX
```
