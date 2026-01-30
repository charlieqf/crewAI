# WeCom ChatGPT Bot -> OpenCode/OMO Integration Debug Log

## Date: 2026-01-27

## Problem Statement

The WeCom AI bot system has a ChatGPT bot that is configured to proxy requests to OpenCode (via `CHATGPT_PROXY_OPENCODE=1` environment variable). When users send messages to `@chatgpt` in WeCom, the bot should:

1. Receive the message via WeCom callback
2. Forward it to OpenCode server (running on localhost:4096)
3. Get the AI response from OpenCode (which uses OhMyOpenCode/Sisyphus agent)
4. Return the response to the user in WeCom

**Symptom**: The bot was returning "OpenCode returned an empty response." for all messages.

---

## Root Causes Identified

### 1. OpenCode Zen API Rate Limiting (FIXED)
- **Issue**: The OpenCode Zen API was returning "Too Many Requests" errors
- **Solution**: User added $20 credits to their Zen API account
- **Status**: RESOLVED

### 2. OpenCode `/message` Endpoint Behavior
- **Issue**: The `/message` POST endpoint is **synchronous** - it waits for the entire agentic loop to complete before returning the HTTP response body
- **Behavior**: 
  - Returns HTTP 200 immediately (headers)
  - Holds connection open waiting for agent to finish
  - Only returns body after all tool calls, LLM responses complete
  - Can take 1-5+ minutes for complex agent workflows
- **Impact**: Our 15-60 second timeouts would expire before getting a response

### 3. Session Caching Issue (FIXED)
- **Issue**: Old invalid session IDs were cached in `/var/lib/wecom-callback/opencode_sessions.json`
- **Solution**: Deleted the cache file to force fresh session creation
- **Status**: RESOLVED

### 4. Polling Logic Bug (PARTIALLY FIXED)
- **Issue**: The polling code was returning OLD assistant messages instead of waiting for NEW responses
- **Root Cause**: `seen_message_ids` was correctly tracking existing messages, but we weren't verifying that our user message was in the session before accepting assistant responses
- **Fix Applied**: Added `our_message_seen` flag to only accept assistant messages that appear AFTER our user message is confirmed in the session
- **Status**: FIX DEPLOYED, NEEDS VERIFICATION

---

## Architecture Overview

```
WeCom User -> WeCom Server -> wecom-callback (Python/FastAPI) 
    -> OpenCodeClient -> OpenCode Server (localhost:4096)
    -> OhMyOpenCode Plugin -> Sisyphus Agent -> LLM (Claude Opus via Zen API)
```

### Key Files

1. **`src/crewai_enterprise/server/aibot_callback.py`**
   - Main bot callback handler
   - `_call_opencode_async()` - async function that calls OpenCode
   - `_should_proxy_chatgpt_to_opencode()` - checks env var

2. **`src/crewai_enterprise/server/opencode_client.py`**
   - `OpenCodeClient` class for HTTP communication with OpenCode
   - `prompt_interactive_with_polling()` - NEW method that:
     - Sends message with short timeout
     - Polls `/session/{id}/message` for responses
     - Checks `/session/status` for idle state

3. **`src/crewai_enterprise/server/session_store.py`**
   - Maps WeCom `chat_id` to OpenCode `session_id`
   - Persists to `/var/lib/wecom-callback/opencode_sessions.json`

### Environment Configuration

On Kamatera server (`104.238.213.119`):

```bash
# /etc/wecom-callback/env
CHATGPT_PROXY_OPENCODE=1
OPENCODE_URL=http://localhost:4096  # (default)

# OpenCode auth
~/.local/share/opencode/auth.json  # Contains Zen API key

# OpenCode config  
~/.config/opencode/opencode.json  # OhMyOpenCode plugin config
```

---

## What Works

1. **OpenCode server is running** on port 4096
2. **Session creation** (`POST /session`) works
3. **Zen API is funded** and responding
4. **Interactive OpenCode** works fine (CLI mode)
5. **Message polling** correctly fetches messages from session
6. **Session status check** works (returns empty dict when idle)

---

## Current State (as of 2026-01-27 ~03:00 PST)

### Latest Fix Deployed

The polling logic now:
1. Records all existing message IDs before sending
2. Sends POST to `/message` with 15s timeout (will timeout, expected)
3. Polls every 2 seconds for up to 180 seconds
4. Waits for OUR user message to appear in session first
5. Only then accepts NEW assistant messages as the response
6. Breaks when session is idle AND we have a response
7. **NEW**: Also breaks if response text has been stable for 10+ seconds (even if session still "busy")

### Issue Fixed: Second Question Gets Stuck

**Problem**: First question works, but second question shows "思考中..." indefinitely.

**Root Cause**: After getting valid response text, we wait for session to become "idle" - but Sisyphus keeps session "busy" for a long time doing additional agent work (tool calls, reflection, etc.) even after the user-facing response is ready.

**Solution Applied**: Added `response_stable_timeout` (10 seconds) - if we have response text and it hasn't changed for 10 seconds, we return it even if session is still "busy". This was the missing piece.

### Code Changes (2026-01-27)

In `prompt_interactive_with_polling()`:
```python
first_response_time = None  # Track when we first got a response
response_stable_timeout = 10.0  # If response unchanged for this long, return it

# ... in polling loop ...

# If we have text and it's been stable for response_stable_timeout, return it
if last_text and first_response_time:
    stable_duration = time.time() - first_response_time
    if stable_duration > response_stable_timeout:
        logger.info(f"[OPENCODE_CLIENT] Response stable for {stable_duration:.1f}s, breaking")
        break
```

Also fixed: Removed duplicate `except Exception` block that was causing LSP errors.

---

## Next Steps to Verify

### 1. Test Fresh Session Response
```bash
# Send a new message to @chatgpt in WeCom
# Check logs:
ssh -i ~/.ssh/kamatera root@104.238.213.119 \
  "journalctl -u wecom-callback --since '5 min ago' --no-pager | grep -i OPENCODE"
```

**Expected logs:**
```
[OPENCODE_CLIENT] Session has X existing messages
[OPENCODE_CLIENT] Sending POST to ...
OpenCode message request timed out (expected), polling for response
[OPENCODE_CLIENT] Our user message msg_xxx is now in session
[OPENCODE_CLIENT] Got new assistant text: <actual response>
[OPENCODE_CLIENT] Session is idle and we have response, breaking
[OPENCODE] Polling succeeded with N chars
```

### 2. Verify Message Order in Session
```bash
ssh -i ~/.ssh/kamatera root@104.238.213.119 'curl -s "http://localhost:4096/session/SESSION_ID/message" | python3 -c "
import sys,json
msgs=json.load(sys.stdin)
for m in msgs[-10:]:
    role = m[\"info\"][\"role\"]
    msg_id = m[\"info\"][\"id\"][:30]
    parts = m.get(\"parts\", [])
    text_parts = [p for p in parts if p.get(\"type\") == \"text\"]
    txt = text_parts[0].get(\"text\", \"\")[:60] if text_parts else \"no text\"
    print(f\"{role}: {msg_id} -> {txt}\")
"'
```

### 3. Check OpenCode Server Logs
```bash
ssh -i ~/.ssh/kamatera root@104.238.213.119 \
  "tail -100 \$(ls -t ~/.local/share/opencode/log/*.log | head -1)"
```

Look for:
- `service=llm` entries showing LLM calls
- `service=session.prompt` showing message processing
- Any `ERROR` entries

---

## Potential Issues Still to Investigate

### 1. Message ID Format
Our code generates `msg_{wecom_msg_id}` but OpenCode generates `msg_bfXXXXXX` format. Need to verify the matching works.

### 2. Agent Response Timing
Sisyphus agent with Claude Opus can take 30-120+ seconds. Current `max_wait=180s` should be enough but may need adjustment.

### 3. Multiple Assistant Messages
OpenCode may generate multiple assistant messages during one turn (e.g., thinking, tool calls, final response). We currently return the LAST text seen - this should be correct but verify.

### 4. Session Corruption
If a session gets into a bad state (too many messages, agent stuck), may need to:
```bash
rm /var/lib/wecom-callback/opencode_sessions.json
systemctl restart wecom-callback
```

---

## Quick Commands Reference

### SSH and Basic Operations
```bash
# SSH to server
ssh -i ~/.ssh/kamatera root@104.238.213.119

# Check service status
systemctl status wecom-callback
systemctl status opencode

# Restart services
systemctl restart wecom-callback
systemctl restart opencode
```

### Log Viewing
```bash
# View wecom-callback logs (live)
journalctl -u wecom-callback -f --no-pager

# View wecom-callback logs (last 5 min, filtered)
journalctl -u wecom-callback --since '5 min ago' --no-pager | grep -i OPENCODE

# View OpenCode server logs
tail -f $(ls -t ~/.local/share/opencode/log/*.log | head -1)

# View last 100 lines of OpenCode logs
tail -100 $(ls -t ~/.local/share/opencode/log/*.log | head -1)
```

### OpenCode API Testing
```bash
# List all sessions
curl -s http://localhost:4096/session | python3 -m json.tool

# Check session status (busy/idle)
curl -s http://localhost:4096/session/status | python3 -m json.tool

# Check provider info
curl -s http://localhost:4096/provider | python3 -m json.tool

# Get messages from a specific session
curl -s "http://localhost:4096/session/SESSION_ID/message" | python3 -m json.tool

# Pretty print last 10 messages from a session
curl -s "http://localhost:4096/session/SESSION_ID/message" | python3 -c "
import sys,json
msgs=json.load(sys.stdin)
for m in msgs[-10:]:
    role = m['info']['role']
    msg_id = m['info']['id'][:30]
    parts = m.get('parts', [])
    text_parts = [p for p in parts if p.get('type') == 'text']
    txt = text_parts[0].get('text', '')[:60] if text_parts else 'no text'
    print(f'{role}: {msg_id} -> {txt}')
"
```

### Session Management
```bash
# Clear session cache (forces new sessions on next request)
rm /var/lib/wecom-callback/opencode_sessions.json

# View current session mappings
cat /var/lib/wecom-callback/opencode_sessions.json | python3 -m json.tool
```

### Deployment Commands (from local Windows machine)
```bash
# Deploy opencode_client.py
scp -i ~/.ssh/kamatera src/crewai_enterprise/server/opencode_client.py \
  root@104.238.213.119:/opt/wecom-callback/src/crewai_enterprise/server/

# Deploy aibot_callback.py
scp -i ~/.ssh/kamatera src/crewai_enterprise/server/aibot_callback.py \
  root@104.238.213.119:/opt/wecom-callback/src/crewai_enterprise/server/

# Deploy and restart (one-liner)
scp -i ~/.ssh/kamatera src/crewai_enterprise/server/opencode_client.py \
  root@104.238.213.119:/opt/wecom-callback/src/crewai_enterprise/server/ && \
ssh -i ~/.ssh/kamatera root@104.238.213.119 "systemctl restart wecom-callback"

# Deploy, restart, and tail logs
scp -i ~/.ssh/kamatera src/crewai_enterprise/server/opencode_client.py \
  root@104.238.213.119:/opt/wecom-callback/src/crewai_enterprise/server/ && \
ssh -i ~/.ssh/kamatera root@104.238.213.119 "systemctl restart wecom-callback && journalctl -u wecom-callback -f --no-pager"
```

### Debugging Specific Issues
```bash
# Check if OpenCode is receiving requests (look for service=session.prompt)
grep "session.prompt" $(ls -t ~/.local/share/opencode/log/*.log | head -1)

# Check LLM calls and responses
grep "service=llm" $(ls -t ~/.local/share/opencode/log/*.log | head -1)

# Check for errors in OpenCode
grep -i "error\|ERROR" $(ls -t ~/.local/share/opencode/log/*.log | head -1) | tail -20

# Monitor both logs simultaneously (use tmux or two terminals)
# Terminal 1: journalctl -u wecom-callback -f --no-pager | grep OPENCODE
# Terminal 2: tail -f $(ls -t ~/.local/share/opencode/log/*.log | head -1)
```

---

## Code Changes Made (Not Yet Committed)

### `opencode_client.py`
- Added `prompt_interactive_with_polling()` method
- Added `get_session_messages()` method  
- Added `get_session_status()` method
- Added extensive logging with `[OPENCODE_CLIENT]` prefix
- Fixed: Track `our_message_seen` before accepting assistant responses
- Fixed: Handle empty session status dict as "idle"

### `aibot_callback.py`
- Changed `run_prompt()` to use polling approach first
- Added `[OPENCODE]` logging prefix
- Increased `max_wait` to 180 seconds
- Falls back to streaming then sync if polling fails

---

## Success Criteria

The integration is working when:
1. User sends `@chatgpt what is 2+2` in WeCom
2. Bot shows "思考中..." (thinking)
3. After 5-30 seconds, bot responds with the correct answer (e.g., "4" or "2+2=4")
4. Response is specific to the question asked (not a generic greeting)
5. Conversation history is maintained within the session

---

## NEW Incident: Rapid Zen API Burn + Stuck "Thinking" (2026-01-27 ~18:20 PST)

### Symptoms
1. **Zen API balance draining ~$0.1/sec** with no user action.
2. **WeCom stuck at "思考中..."** for simple prompts (e.g. "do you know agent Librarian?").
3. Responses sometimes **leak chain-of-thought / meta** (e.g. "Responding to a simple math query...").
4. Intermittent **empty response** from OpenCode `/message` (200 OK but empty body).

### Findings (Root Causes / Strong Signals)
1. **OpenCode session loop**: OpenCode server logs showed repeated `session.prompt step=... loop` for a single session.
   - Session ID observed: `ses_3fe1709efffeURFeNt7h1UvUDw` (previous loop) and later `ses_3fd891d98ffetoSuRBrrX2BdPz`.
2. **Assistant messages created with ONLY reasoning/tool parts (no text)**:
   - WeCom bridge waits for `text` parts to finish; if OpenCode emits only `reasoning` or `tool` parts, it stays stuck.
3. **Reasoning leakage**:
   - OpenCode SDK returns `reasoning` parts; current `_extract_opencode_text()` includes reasoning in text.
4. **Session mapping cache**:
   - WeCom callback caches session in memory. Deleting session file alone won't reset until service restart.

### Immediate Mitigations Applied
1. **Disabled ralph-loop hook** in OMO config:
   - `/root/.config/opencode/oh-my-opencode.json` now includes `disabled_hooks: ["ralph-loop"]`.
2. **Deleted looping session data**:
   - Removed `ses_3fe1709efffeURFeNt7h1UvUDw` from OpenCode storage.
3. **Restarted services** to clear in-memory mappings:
   - `systemctl restart opencode`
   - `systemctl restart wecom-callback`

### Remaining Problems
1. **Stuck "思考中..."** still happens when OpenCode is "busy" but never emits a `text` part.
2. **Reasoning leakage** in responses from OpenCode.
3. **Empty response** 200 OK from `/message` in some cases.

---

## 2026-01-28 Update: Message ID Ordering Bug (FIXED)

### Symptom
- First prompt sometimes OK, then later prompts get stuck at "思考中...".
- OpenCode `session.prompt` loop exits immediately (no new assistant message).

### Root Cause
- WeCom bridge was **sending custom `messageID`** (derived from WeCom msg ids).
- OpenCode loop exits when `lastUser.id < lastAssistant.id`. Our custom IDs are **not monotonic**, so OpenCode thought the assistant already responded and exited without creating a new assistant message.

### Fix Applied (Deployed)
- **Do NOT send `messageID`** to OpenCode. Let OpenCode generate its own ordered IDs.
- Keep session reuse and abort-if-busy behavior.

### Result
- Multiple back-to-back prompts in the same session now respond correctly.
- Recent logs show normal `POST /message` -> `complete` flow with valid responses.

---

## 2026-01-28 Update: OMO Main Agent Cost Control (Active)

### Decision
- Keep OMO main agent on **`opencode/gpt-5-nano`** (cheaper) while validating the "rapid token burn" issue is gone.
- Switch to **Claude Opus 4.5** only after stability is confirmed.

### Current OMO Agent Mapping
- `sisyphus` (main): `opencode/gpt-5-nano`
- `oracle`: `opencode/gpt-5.2-codex`
- `librarian`: `opencode/claude-sonnet-4-5`
- `planner`: `opencode/claude-sonnet-4-5`
- `explore`: `opencode/gpt-5-nano`

---

## 2026-01-28 Update: Busy-Session Handling, /force, /file-html (DEPLOYED)

### Symptoms Observed
1. **"OpenCode session is still busy after abort"** when sending a new message.
2. **WeCom shows a short snippet only** (e.g., "让我重新调用：" or a lead-in line).
3. **/file-html sometimes returns a short/partial HTML** (missing the full report).
4. **Reply appears in OpenCode session** but not fully shown in WeCom.

### Root Causes / Signals
1. **Session busy even after abort** when agent continues tool steps; OpenCode session state doesn't flip to idle promptly.
2. **Response selection was too eager** (taking the first/last short text snippet).
3. **/file-html pulled the wrong assistant text** (matched the wrong user prompt or used a partial response).

### Fixes Applied (Deployed)
1. **Busy-session guard (mirrors UI behavior)**:
   - If session is busy, we abort before sending a new prompt.
   - Wait briefly; if still busy and not `force`, return a clear busy message.
2. **`/force` command**:
   - `/force <prompt>` aborts the busy session and proceeds.
   - If still busy, fallback creates a new session (context loss is explicit).
   - Nested `/force /file-html ...` now works.
3. **Response completeness heuristics**:
   - Increased `max_wait` to **280s** (WeCom limit ~300s).
   - `response_stable_timeout` increased to **20s**.
   - Added "incomplete reply" heuristics: short outputs, lead-in lines, or trailing colon -> continue waiting.
   - When ending a turn, choose the **longest assistant text** seen after our user prompt.
4. **/file-html pipeline hardening**:
   - Wait for session idle (up to 280s) before building HTML.
   - Choose assistant text **matching our request time + content**; then select the longest response.
   - Generate HTML and upload to Qiniu; return only the link.

### Current Status
- Simple prompts: mostly stable.
- Complex prompts: WeCom sometimes still shows a short snippet, but HTML output is closer to full content.
  - The remaining gap likely comes from **early selection** or **multi-message assistant output**.

---

## 2026-01-28 Update: OMO Re-enabled + ralph-loop Restored (Active)

### State
- OMO plugin re-enabled in `/root/.config/opencode/opencode.json`.
- `ralph-loop` hook re-enabled (removed from `disabled_hooks`).
- Sisyphus remains on `opencode/gpt-5-nano` until token burn stays stable.

---

## Latest Troubleshooting Commands

### ⚠️ PowerShell vs Bash gotchas (avoid “head not recognized”)
When running remote Linux commands from **Windows PowerShell**, remember:
- Local shell is PowerShell; remote shell is bash. PowerShell tries to parse pipes like `| head -1` unless you quote it correctly.
- **Use `bash -lc` on the remote** for complex pipelines.
- **Avoid `head`/`tail` locally**; they exist only on the Linux side.
- **PowerShell’s `--%`** can help pass literal strings to `ssh` without parsing.

**Good patterns:**
```powershell
# Run complex pipelines safely on remote (recommended)
ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'ls -t /root/.local/share/opencode/log/*.log | head -1'"

# Use --% to stop PowerShell parsing
ssh --% -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'tail -200 /root/.local/share/opencode/log/2026-01-28T025425.log'"
```

**Bad pattern (PowerShell interprets `head` locally):**
```powershell
ssh -i ~/.ssh/kamatera root@104.238.213.119 "tail -200 $(ls -t ~/.local/share/opencode/log/*.log | head -1)"
```

### Helper commands (copy/paste safe on Windows PowerShell)
```powershell
# Get latest OpenCode log file (safe)
ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'ls -t /root/.local/share/opencode/log/*.log | head -1'"

# Tail latest OpenCode log (safe)
ssh -i ~/.ssh/kamatera root@104.238.213.119 "bash -lc 'tail -200 $(ls -t /root/.local/share/opencode/log/*.log | head -1)'"

# Show session messages (raw JSON, safe)
ssh -i ~/.ssh/kamatera root@104.238.213.119 "curl -s http://localhost:4096/session/SESSION_ID/message | head -c 800"
```

### Optional: create a tiny helper script on Windows
Create `scripts/opencode-log.ps1` (local) to avoid quoting issues:
```powershell
param(
  [string]$Host="104.238.213.119",
  [string]$User="root",
  [string]$Key="~/.ssh/kamatera"
)
ssh -i $Key $User@$Host "bash -lc 'ls -t /root/.local/share/opencode/log/*.log | head -1'"
ssh -i $Key $User@$Host "bash -lc 'tail -200 $(ls -t /root/.local/share/opencode/log/*.log | head -1)'"
```
Then run:
```powershell
.\scripts\opencode-log.ps1
```

### New helper scripts (recommended)
Use the local wrappers in `scripts/opencode_debug/` to avoid PowerShell quoting pitfalls:
- `oc-session-summary.ps1` / `.sh` to detect **which assistant reply is tied to the latest user** and whether it has any `text` parts.
- `oc-diag.ps1` / `.sh` to capture logs + status + latest session in one go.

If you see:
```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```
It usually means **empty or non-JSON response** (timeout or upstream error). Check logs and retry.

### 1) Identify looping sessions and LLM calls
```bash
# OpenCode log (latest)
ls -t ~/.local/share/opencode/log | head -1
tail -200 ~/.local/share/opencode/log/$(ls -t ~/.local/share/opencode/log | head -1)

# Look for agent loop activity
grep "session.prompt step" ~/.local/share/opencode/log/$(ls -t ~/.local/share/opencode/log | head -1) | tail -100
```

### 2) Check OpenCode session status
```bash
curl -i http://localhost:4096/session/status
```
If status shows `{"session_id":{"type":"busy"}}` but no response arrives, OpenCode may be stuck emitting only reasoning/tool parts.

### 3) Inspect session messages (fast)
```bash
curl -i http://localhost:4096/session/SESSION_ID/message | head -40
```
Look for:
- **assistant** messages with `parts.type == "text"`
- If only `reasoning` / `tool` / `step-*` parts exist, WeCom will stay in "thinking".

### 4) Check if assistant text exists for latest user prompt
```bash
curl -s http://localhost:4096/session/SESSION_ID/message | python3 - <<'PY'
import sys, json
msgs=json.load(sys.stdin)
last_user=None
last_ts=-1
for m in msgs:
    info=m.get("info",{})
    if info.get("role")!="user":
        continue
    ts=info.get("time",{}).get("created") or 0
    if ts>last_ts:
        last_ts=ts
        last_user=m
if not last_user:
    print("no user message")
    raise SystemExit
parent_id=last_user.get("info",{}).get("id")
assist=[m for m in msgs if (m.get("info",{}).get("parentID")==parent_id or m.get("info",{}).get("parentId")==parent_id)]
print("latest_user", parent_id, "assistant replies", len(assist))
for m in assist[-5:]:
    parts=m.get("parts",[])
    types=[p.get("type") for p in parts]
    text=""
    for p in parts:
        if p.get("type")=="text":
            text=p.get("text","")[:120].replace("\\n"," ")
            break
    print("types", types, "text", text)
PY
```

### 5) Reset stuck sessions
```bash
# Remove chat mapping (forces new session)
python3 - <<'PY'
import json
path="/var/lib/wecom-callback/opencode_sessions.json"
chat_id="wrQakDCgAAPARKEiyS8Cg3fLSciZUwWw"  # replace
with open(path,'r') as f:
    data=json.load(f)
if chat_id in data:
    data.pop(chat_id)
    with open(path,'w') as f:
        json.dump(data,f,indent=2)
    print("removed chat mapping")
PY

# Restart to clear in-memory cache
systemctl restart wecom-callback
```

### 6) Delete a looping OpenCode session
```bash
SESSION="ses_XXXXXXXXXXXX"
BASE="/root/.local/share/opencode/storage"
MSGDIR="$BASE/message/$SESSION"
if [ -d "$MSGDIR" ]; then
  for f in "$MSGDIR"/*.json; do
    mid=$(basename "$f" .json)
    rm -rf "$BASE/part/$mid"
  done
  rm -rf "$MSGDIR"
fi
rm -f "$BASE/session/5b0cb53f3d1aca39a750a401f9e5d51a0c3fed55/$SESSION.json"
echo "deleted session data for $SESSION"
```

### 7) Verify WeCom bot path and OpenCode polling
```bash
journalctl -u wecom-callback --since '10 min ago' --no-pager | grep -i OPENCODE
```

---

## Proposed Code Fixes (Not Yet Applied)

1. **Final-only output guard**:
   - In `_extract_opencode_text()` remove `reasoning` parts.
   - Add a hard instruction to OpenCode prompt: "Return only final answer. No reasoning or meta."
2. **Auto-rotate sessions** on repeated no-text responses:
   - If no assistant `text` for N seconds, create a new session and retry once.
3. **Reasoning leakage filter**:
   - Strip known boilerplate like "Responding to..." when detected.

---

## Action Plan / Next Steps (Clear Owner + Sequence)

### A) Immediate Ops (On-call)
1. **If Zen burn spikes**: `systemctl stop wecom-callback && systemctl stop opencode`
2. **Check OpenCode loops**: use `grep "session.prompt step"` on latest log.
3. **Reset stuck session**:
   - Remove chat mapping in `/var/lib/wecom-callback/opencode_sessions.json`
   - Delete looping session from `/root/.local/share/opencode/storage`
   - Restart `wecom-callback`

### B) Engineering Fix (Dev)
1. **Implement final-only guard** in `aibot_callback.py`:
   - Ignore `reasoning` parts in `_extract_opencode_text()`
2. **Add prompt hardening**:
   - Append "Return only final answer. No reasoning or meta."
3. **Auto-rotate session** if no `text` parts after N seconds.

### C) Verification (QA/Dev)
1. Send: `@chatgpt 2+2` → expect `4` only (no meta).
2. Send: `@chatgpt do you know Librarian` → expect short response, no "思考中..." hang.
3. Check logs:
   - `journalctl -u wecom-callback --since '5 min ago' --no-pager | grep -i OPENCODE`
   - Ensure no repeated `session.prompt step=... loop`.

---

## OMO Disable / Re-enable Procedure (OpenCode Core Only)

### When to use
Use this to isolate whether loops and "thinking" hangs are caused by OMO plugins vs OpenCode core.

### Disable OMO (temporary)
1. Edit OpenCode config:
```bash
cat /root/.config/opencode/opencode.json
```
2. Set plugin list to empty:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": []
}
```
3. Restart OpenCode:
```bash
systemctl restart opencode
```

### Re-enable OMO later
1. Restore plugin list:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["oh-my-opencode"]
}
```
2. Restart OpenCode:
```bash
systemctl restart opencode
```

### Verification
Send a simple prompt and confirm:
- Response returns quickly
- No "session.prompt step=... loop" spam
- No reasoning leakage
