# OpenCode Task Context Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/context:<window>` support for /task create/append to fetch WeCom chat history, store raw context as a sidecar file, append a compact summary to TaskMessage, and inject a context block into the OpenCode prompt.

**Architecture:** Parse context flags at command handling, store context metadata on TaskInput, let the worker fetch WeCom context per input, write raw messages to a task-local context file, append a system summary to TaskMessage, and prepend a short context block to the prompt.

**Tech Stack:** FastAPI, SQLite, Python worker loop, filesystem storage, WeCom archive APIs.

---

### Task 1: Add context window parsing utility

**Files:**
- Create: `src/crewai_enterprise/utils/context_window.py`
- Test: `tests/utils/test_context_window.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.utils.context_window import parse_context_window


def test_parse_context_window_days():
    assert parse_context_window("1d") == 86400


def test_parse_context_window_hours():
    assert parse_context_window("6h") == 21600


def test_parse_context_window_weeks():
    assert parse_context_window("2w") == 1209600


def test_parse_context_window_invalid():
    assert parse_context_window("oops") is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/utils/test_context_window.py -v`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
import re


def parse_context_window(value: str) -> int | None:
    match = re.fullmatch(r"(\d+)([hdw])", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {"h": 3600, "d": 86400, "w": 604800}[unit]
    return amount * seconds
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/utils/test_context_window.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/utils/test_context_window.py src/crewai_enterprise/utils/context_window.py
git commit -m "feat: add context window parser"
```

---

### Task 2: Extend task input schema with context metadata

**Files:**
- Modify: `src/crewai_enterprise/server/task_store.py`
- Test: `tests/server/test_task_store.py` (create if missing)

**Step 1: Write the failing test**

```python
def test_task_input_stores_context_fields(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    store.init_schema()
    task_id = store.create_task("chat", "user", "title")
    input_id = store.append_input(task_id, "hello", "wecom", context_source="wecom", context_window=86400)
    inp = store.get_input(input_id)
    assert inp["context_source"] == "wecom"
    assert inp["context_window"] == 86400
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_task_store.py::test_task_input_stores_context_fields -v`
Expected: FAIL

**Step 3: Write minimal implementation**

- Add `context_source` and `context_window` columns to `task_input` table (with back-compat `ALTER TABLE` checks).
- Extend `append_input` signature to accept context metadata.
- Add `get_input` helper to read a single input row for tests.

**Step 4: Run test to verify it passes**

Run: `pytest tests/server/test_task_store.py::test_task_input_stores_context_fields -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/task_store.py tests/server/test_task_store.py
git commit -m "feat: store task input context metadata"
```

---

### Task 3: Parse /context flag in task commands

**Files:**
- Modify: `src/crewai_enterprise/server/handlers/task_commands.py`
- Modify: `src/crewai_enterprise/server/handlers/task_handler.py`
- Test: `tests/server/test_task_commands.py`

**Step 1: Write the failing tests**

```python
def test_parse_task_command_accepts_task_id_without_space():
    cmd = parse_task_command("/task6 do work")
    assert cmd["type"] == "append"
    assert cmd["task_id"] == 6
    assert cmd["text"] == "do work"


def test_parse_context_flag():
    cmd = parse_task_command("/task /context:1d do work")
    assert cmd["context_window"] == 86400
    assert cmd["text"] == "do work"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_task_commands.py -v`
Expected: FAIL

**Step 3: Implement parsing**

- Accept `/task<id> <text>` (require a space after id).
- Extract `/context:<window>` flag; remove it from text; parse via `parse_context_window`.
- Return `context_window` (seconds) and `context_source="wecom"` when present.
- Thread through `task_handler` to `append_input`.

**Step 4: Run tests to verify pass**

Run: `pytest tests/server/test_task_commands.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/handlers/task_commands.py src/crewai_enterprise/server/handlers/task_handler.py tests/server/test_task_commands.py
git commit -m "feat: parse /context flag and task id shorthand"
```

---

### Task 4: Add WeCom context fetch + summary generation

**Files:**
- Create: `src/crewai_enterprise/utils/wecom_context.py`
- Test: `tests/utils/test_wecom_context.py`

**Step 1: Write the failing test**

```python
def test_context_summary_from_messages():
    messages = [
        {"created_at": "2026-02-01 10:00:00", "sender": "u1", "text": "hello"},
        {"created_at": "2026-02-01 10:01:00", "sender": "u2", "text": "world"},
    ]
    summary = build_context_summary(messages, "2026-02-01 00:00:00", "2026-02-02 00:00:00")
    assert summary["count"] == 2
    assert "hello" in summary["first"]
    assert "world" in summary["last"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/utils/test_wecom_context.py -v`
Expected: FAIL

**Step 3: Implement minimal summary**

- `build_context_summary(messages, start, end)` returns dict with `count`, `start`, `end`, `first`, `last`.
- Truncate previews to a fixed length (e.g., 120 chars).

**Step 4: Run tests**

Run: `pytest tests/utils/test_wecom_context.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/utils/wecom_context.py tests/utils/test_wecom_context.py
git commit -m "feat: add wecom context summary builder"
```

---

### Task 5: Worker writes context file + summary TaskMessage + prompt injection

**Files:**
- Modify: `src/crewai_enterprise/server/task_worker.py`
- Modify: `src/crewai_enterprise/server/task_store.py`
- Modify: `src/crewai_enterprise/server/task_viewer.py` (summary rendering)
- Test: `tests/server/test_task_worker.py`

**Step 1: Write failing test**

```python
def test_worker_appends_context_summary(tmp_path, monkeypatch):
    # stub context fetch to return messages
    # ensure TaskMessage includes system summary and context file path
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_task_worker.py::test_worker_appends_context_summary -v`
Expected: FAIL

**Step 3: Implement minimal worker changes**

- Fetch context when `context_window` exists on input.
- Write raw messages to `{task_dir}/context/wecom-<ts>.json`.
- Append TaskMessage role=`system` with summary and file path.
- Prepend `SYSTEM CONTEXT` block in prompt.
- Update viewer to render summary block and link to the context file.

**Step 4: Run tests**

Run: `pytest tests/server/test_task_worker.py::test_worker_appends_context_summary -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/task_worker.py src/crewai_enterprise/server/task_store.py src/crewai_enterprise/server/task_viewer.py tests/server/test_task_worker.py
git commit -m "feat: inject wecom context into task runs"
```

---

### Task 6: Update WeCom reply copy

**Files:**
- Modify: `src/crewai_enterprise/server/handlers/task_handler.py`
- Test: `tests/server/test_task_handler.py`

**Step 1: Write failing test**

```python
def test_reply_includes_context_acknowledgement():
    reply = handle_task_command("/task /context:1d do work", "chat", "user")
    assert "已包含" in reply
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_task_handler.py::test_reply_includes_context_acknowledgement -v`
Expected: FAIL

**Step 3: Implement reply text**

- Append: `（已包含 YYYY-MM-DD HH:mm 至 YYYY-MM-DD HH:mm 的聊天上下文）`.
- Use parsed window to compute start/end in server time (UTC+8).

**Step 4: Run tests**

Run: `pytest tests/server/test_task_handler.py::test_reply_includes_context_acknowledgement -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/handlers/task_handler.py tests/server/test_task_handler.py
git commit -m "feat: acknowledge context window in task reply"
```

---

### Task 7: Docs

**Files:**
- Modify: `company_docs/wecom_task_link_design.md`
- Modify: `ops/daily_ops_runbook.md`

**Step 1: Update docs**

- Document `/context:<window>` behavior and the context summary block.
- Note the context files are stored under task directory `context/`.

**Step 2: Commit**

```bash
git add company_docs/wecom_task_link_design.md ops/daily_ops_runbook.md
git commit -m "docs: document task context window" 
```
