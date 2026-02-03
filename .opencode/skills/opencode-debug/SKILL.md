---
name: opencode-debug
description: OpenCode debugging and diagnostics: tail logs, inspect sessions/messages, diagnose wecom-callback issues, and fetch session data via HTTP. Use when investigating OpenCode runtime problems, session issues, log triage, or when needing quick diagnostics across PowerShell, bash, or Python.
---

# OpenCode Debugging

Pick the script that matches where you are running:

- Windows workstation: PowerShell scripts in `scripts/opencode_debug/*.ps1`.
- Server shell: Bash scripts in `scripts/opencode_debug/*.sh`.
- Any machine with network access: `scripts/opencode_debug/oc_session_dump.py`.

## Common workflows

1) Tail latest OpenCode log

- PowerShell: `scripts/opencode_debug/oc-log-tail.ps1`
- Bash: `scripts/opencode_debug/oc-log-tail.sh`

2) Check current session status

- PowerShell: `scripts/opencode_debug/oc-session-status.ps1`
- Bash: `scripts/opencode_debug/oc-session-status.sh`

3) Inspect session messages

- PowerShell: `scripts/opencode_debug/oc-session-messages.ps1 -SessionId ses_XXXX`
- Bash: `scripts/opencode_debug/oc-session-messages.sh ses_XXXX`
- Summary: `scripts/opencode_debug/oc-session-summary.ps1` or `scripts/opencode_debug/oc-session-summary.sh`
- Assistant-only storage dump: `scripts/opencode_debug/oc-storage-session-assistant.ps1` or `scripts/opencode_debug/oc-storage-session-assistant.sh`

4) One-shot diagnostics

- PowerShell (remote server): `scripts/opencode_debug/oc-diag.ps1 -Minutes 15 -Lines 200 -Limit 10`
- Bash (on server): `scripts/opencode_debug/oc-diag.sh 15 200 10`

5) Fetch session status/messages via HTTP

- `python3 scripts/opencode_debug/oc_session_dump.py --status`
- `python3 scripts/opencode_debug/oc_session_dump.py --session ses_XXXX --limit 10`

## Error handling

- If you see JSON decode errors or empty responses, re-run log tailing and wecom-callback logs to confirm upstream status.
- The scripts are designed to be copy/paste-safe and avoid shell quoting issues; prefer them over ad-hoc commands.
