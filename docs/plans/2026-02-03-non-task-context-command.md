# Non-Task /context Prefix Command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow normal (non-/task) WeCom chat messages to use `/context:<window>` when the message starts with `/`, applying a WeCom context window before the LLM runs.

**Architecture:** Parse prefix commands in the WeCom text handler before calling OpenCode/LLM. If the message begins with `/`, scan leading `/` tokens, capture the last `/context:<window>` token, strip all `/context:*` tokens, and prepend a WeCom context block to the prompt. Reuse `parse_context_window` and `fetch_wecom_chat_context` utilities from the task flow.

**Tech Stack:** FastAPI, Python async handlers, WeCom context utilities, OpenCode client.

---

### Task 1: Add prefix command parsing helper

**Files:**
- Create: `src/crewai_enterprise/server/handlers/context_prefix.py`
- Test: `tests/server/test_context_prefix.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.server.handlers.context_prefix import extract_context_prefix


def test_extract_context_prefix_requires_leading_slash():
    text, window = extract_context_prefix("hello /context:1d")
    assert text == "hello /context:1d"
    assert window is None


def test_extract_context_prefix_uses_last_context_token():
    text, window = extract_context_prefix("/foo /context:1d /bar /context:2h ask")
    assert text == "/foo /bar ask"
    assert window == 7200
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_context_prefix.py -v`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
import re
from src.crewai_enterprise.utils.context_window import parse_context_window


def extract_context_prefix(text: str) -> tuple[str, int | None]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return text, None
    tokens = stripped.split()
    context_window = None
    kept = []
    for token in tokens:
        if not token.startswith("/"):
            kept.append(token)
            kept.extend(tokens[tokens.index(token) + 1 :])
            break
        match = re.match(r"^/context:(\S+)$", token, re.IGNORECASE)
        if match:
            context_window = parse_context_window(match.group(1))
            continue
        kept.append(token)
    return " ".join(kept).strip(), context_window
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_context_prefix.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/handlers/context_prefix.py tests/server/test_context_prefix.py
git commit -m "feat: parse /context prefix in normal chat"
```

---

### Task 2: Inject context into normal chat flow

**Files:**
- Modify: `src/crewai_enterprise/server/aibot_callback.py`
- Test: `tests/server/test_aibot_callback.py`

**Step 1: Write the failing test**

```python
def test_context_prefix_injects_summary(monkeypatch):
    # Use a fake chat_id and stub fetch_wecom_chat_context
    # Ensure the prompt includes a context summary block when /context:1d is used
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_aibot_callback.py::test_context_prefix_injects_summary -v`
Expected: FAIL

**Step 3: Implement minimal injection**

```python
from src.crewai_enterprise.server.handlers.context_prefix import extract_context_prefix
from src.crewai_enterprise.utils.wecom_context import (
    fetch_wecom_chat_context,
    build_context_summary,
    build_context_transcript,
)
```

- In `_call_opencode_async` and `_call_llm_async`, before building `safe_content`, run:
  - `cleaned, window = extract_context_prefix(content)`
  - If `window` is not None: compute `start_dt/end_dt`, call `fetch_wecom_chat_context(chat_id, start, end)`
  - Build a short summary string and prepend to `safe_content`
  - Do **not** emit a separate system reply; it should be silent
- Use last `/context:*` token if multiple exist

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_aibot_callback.py::test_context_prefix_injects_summary -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/aibot_callback.py tests/server/test_aibot_callback.py
git commit -m "feat: inject wecom context in normal chat"
```

---

### Task 3: Add guardrails + docs

**Files:**
- Modify: `company_docs/wecom_callback_deployment_guide.md`
- Modify: `docs/context_append_helper.md`

**Step 1: Update docs**

- Document the prefix rule: only messages starting with `/` are parsed
- Document multi-command behavior and “last /context wins”
- Clarify no user-visible acknowledgement is sent

**Step 2: Commit**

```bash
git add company_docs/wecom_callback_deployment_guide.md docs/context_append_helper.md
git commit -m "docs: describe non-task /context prefix behavior"
```

---

### Task 4: End-to-end verification

**Files:**
- None

**Step 1: Manual test**

Send a WeCom message:
`/context:1d 请总结昨天的对话重点`

Expected:
- No extra “context applied” message
- Reply includes content from the last 1 day

**Step 2: Verify logs**

Run: `journalctl -u wecom-callback --since -5min --no-pager | tail -n 200`
Expected: logs showing context fetch counts

**Step 3: Commit**

```bash
git add .
git commit -m "test: verify non-task /context flow"
```
