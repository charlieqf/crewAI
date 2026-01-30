# WeCom Task Link Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `/task` link-based tasks in WeCom with async OpenCode execution, persistent task storage, and a minimal task web UI.

**Architecture:** Add a Task Service (FastAPI router + SQLite store), a task worker loop that feeds OpenCode and reads output from local storage, and a lightweight task web page that polls task messages and files.

**Tech Stack:** Python 3.10, FastAPI, SQLite (WAL), OpenCodeClient, WeCom webhook

---

### Task 1: Task config + env wiring

**Files:**
- Create: `src/crewai_enterprise/server/task_config.py`
- Modify: `.env.example`
- Test: `tests/server/test_task_config.py`

**Step 1: Write the failing test**

Note: dedupe uses message file ordering; store last seen filename, not message id.

```python
from src.crewai_enterprise.server.task_config import get_task_config


def test_task_config_defaults(monkeypatch):
    monkeypatch.delenv("TASK_BASE_URL", raising=False)
    monkeypatch.delenv("TASK_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("TASK_DB_PATH", raising=False)
    monkeypatch.delenv("OPENCODE_STORAGE_ROOT", raising=False)

    cfg = get_task_config()
    assert cfg.base_url
    assert cfg.storage_root
    assert cfg.db_path.endswith("tasks.db")
    assert "opencode" in cfg.opencode_storage_root
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_config.py -v`
Expected: FAIL with `ImportError` or missing `get_task_config`

**Step 3: Write minimal implementation**

Note: claim inputs with a task-level lock using `BEGIN IMMEDIATE` + `task.status` CAS.

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class TaskConfig:
    base_url: str
    storage_root: str
    db_path: str
    opencode_storage_root: str


def get_task_config() -> TaskConfig:
    base_url = os.getenv("TASK_BASE_URL", "http://127.0.0.1:8080")
    storage_root = os.getenv("TASK_STORAGE_ROOT", "/var/lib/wecom-tasks")
    db_path = os.getenv("TASK_DB_PATH", os.path.join(storage_root, "tasks.db"))
    opencode_storage_root = os.getenv(
        "OPENCODE_STORAGE_ROOT", "/root/.local/share/opencode/storage"
    )
    return TaskConfig(
        base_url=base_url,
        storage_root=storage_root,
        db_path=db_path,
        opencode_storage_root=opencode_storage_root,
    )
```

**Step 4: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add .env.example src/crewai_enterprise/server/task_config.py tests/server/test_task_config.py
git commit -m "feat: add task config defaults"
```

---

### Task 2: Task SQLite schema + store helpers

**Files:**
- Create: `src/crewai_enterprise/server/task_store.py`
- Test: `tests/server/test_task_store.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.server.task_store import TaskStore


def test_task_store_crud(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(str(db_path))
    store.init_schema()

    task_id = store.create_task(
        wecom_chat_id="room1",
        wecom_user_id="user1",
        title="hello",
    )
    store.append_message(task_id, role="user", content="q1", source="wecom")
    store.append_input(task_id, content="q1", source="wecom")

    inp = store.claim_next_input()
    assert inp["task_id"] == task_id
    store.mark_input_done(inp["id"])

    task = store.get_task(task_id)
    assert task["id"] == task_id
    messages = store.list_messages(task_id)
    assert messages[-1]["content"] == "q1"
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_store.py -v`
Expected: FAIL with `ImportError` or missing methods

**Step 3: Write minimal implementation**

```python
import sqlite3
from typing import Any
from src.crewai_enterprise.server.opencode_client import OpenCodeClient


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    wecom_chat_id TEXT,
                    wecom_user_id TEXT,
                    opencode_session_id TEXT,
                    title TEXT,
                    status TEXT DEFAULT 'queued',
                    last_seen_message_file TEXT
                );
                CREATE TABLE IF NOT EXISTS task_message (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task(id)
                );
                CREATE TABLE IF NOT EXISTS task_input (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'pending',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES task(id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_input_task_status
                ON task_input(task_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_task_message_task_time
                ON task_message(task_id, created_at);
                """
            )

    def create_task(self, wecom_chat_id: str, wecom_user_id: str, title: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task(wecom_chat_id, wecom_user_id, title, status)
                VALUES (?, ?, ?, 'queued')
                """,
                (wecom_chat_id, wecom_user_id, title),
            )
            return int(cur.lastrowid)

    def append_message(self, task_id: int, role: str, content: str, source: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO task_message(task_id, role, content, source) VALUES (?, ?, ?, ?)",
                (task_id, role, content, source),
            )
            conn.execute(
                "UPDATE task SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )

    def append_input(self, task_id: int, content: str, source: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO task_input(task_id, content, source) VALUES (?, ?, ?)",
                (task_id, content, source),
            )
            return int(cur.lastrowid)

    def claim_next_input(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT ti.*
                FROM task_input ti
                JOIN task t ON t.id = ti.task_id
                WHERE ti.status='pending' AND t.status!='running'
                ORDER BY ti.created_at
                LIMIT 1
                """
            ).fetchone()
            if not row:
                conn.commit()
                return None
            conn.execute(
                "UPDATE task SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["task_id"],),
            )
            conn.execute(
                "UPDATE task_input SET status='processing' WHERE id=?",
                (row["id"],),
            )
            conn.commit()
            return dict(row)

    def mark_input_done(self, input_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE task_input SET status='done' WHERE id=?",
                (input_id,),
            )
            conn.execute(
                "UPDATE task SET updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT task_id FROM task_input WHERE id=?)",
                (input_id,),
            )

    def update_last_seen_file(self, task_id: int, filename: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE task SET last_seen_message_file=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (filename, task_id),
            )

    def ensure_session(self, task_id: int, client: OpenCodeClient) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT opencode_session_id FROM task WHERE id=?",
                (task_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
            session_id = client.create_session()
            conn.execute(
                "UPDATE task SET opencode_session_id=?, status='running' WHERE id=?",
                (session_id, task_id),
            )
            return session_id

    def list_messages(self, task_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_message WHERE task_id=? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_recent_messages(self, task_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_message WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return list(reversed([dict(r) for r in rows]))

    def pending_count(self, task_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM task_input WHERE task_id=? AND status='pending'",
                (task_id,),
            ).fetchone()
        return int(row[0] or 0)

    def mark_task_done_if_idle(self, task_id: int) -> None:
        if self.pending_count(task_id) == 0:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE task SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (task_id,),
                )

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM task WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None
```

**Step 4: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_store.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/task_store.py tests/server/test_task_store.py
git commit -m "feat: add task sqlite store"
```

---

### Task 3: /task command parsing helpers

**Files:**
- Create: `src/crewai_enterprise/server/handlers/task_commands.py`
- Test: `tests/server/test_task_commands.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.server.handlers.task_commands import parse_task_command


def test_parse_task_create():
    cmd = parse_task_command("/task design a flow")
    assert cmd == {"type": "create", "text": "design a flow"}


def test_parse_task_append():
    cmd = parse_task_command("/task 1234 add note")
    assert cmd == {"type": "append", "task_id": 1234, "text": "add note"}


def test_parse_task_append_empty():
    cmd = parse_task_command("/task 1234")
    assert cmd == {"type": "append", "task_id": 1234, "text": ""}


def test_parse_task_invalid():
    assert parse_task_command("/task") is None
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_commands.py -v`
Expected: FAIL with `ImportError` or missing parser

**Step 3: Write minimal implementation**

```python
import re


def parse_task_command(text: str):
    match = re.match(r"^\s*/task\s+(.*)$", text.strip())
    if not match:
        return None
    rest = match.group(1).strip()
    if not rest:
        return None
    parts = rest.split(maxsplit=1)
    if parts[0].isdigit():
        return {
            "type": "append",
            "task_id": int(parts[0]),
            "text": parts[1] if len(parts) > 1 else "",
        }
    return {"type": "create", "text": rest}
```

**Step 4: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_commands.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/handlers/task_commands.py tests/server/test_task_commands.py
git commit -m "feat: parse /task commands"
```

---

### Task 4: Task Service API router

**Files:**
- Create: `src/crewai_enterprise/server/task_service.py`
- Modify: `src/crewai_enterprise/server/wecom_callback.py`
- Test: `tests/server/test_task_service.py`

**Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app


def test_task_create_and_append(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/task",
        json={"chat_id": "room1", "user_id": "u1", "text": "hello"},
    )
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    res2 = client.post(
        f"/api/task/{task_id}/append",
        json={"chat_id": "room1", "user_id": "u1", "text": "more"},
    )
    assert res2.status_code == 200
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_service.py -v`
Expected: FAIL with 404 or missing router

**Step 3: Write minimal implementation**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore

router = APIRouter()


class CreateTaskIn(BaseModel):
    chat_id: str
    user_id: str
    text: str


class AppendTaskIn(BaseModel):
    chat_id: str
    user_id: str
    text: str


class OutputIn(BaseModel):
    role: str
    content: str
    source: str


@router.post("/api/task")
def create_task(body: CreateTaskIn):
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    store.init_schema()
    title = body.text[:60]
    task_id = store.create_task(body.chat_id, body.user_id, title)
    store.append_message(task_id, "user", body.text, "wecom")
    store.append_input(task_id, body.text, "wecom")
    return {"task_id": task_id, "url": f"{cfg.base_url}/task/{task_id}"}


@router.post("/api/task/{task_id}/append")
def append_task(task_id: int, body: AppendTaskIn):
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    store.append_message(task_id, "user", body.text, "wecom")
    store.append_input(task_id, body.text, "wecom")
    return {"ok": True, "url": f"{cfg.base_url}/task/{task_id}"}


@router.get("/api/task/{task_id}")
def get_task(task_id: int):
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    task = store.get_task(task_id)
    messages = store.list_messages(task_id)
    return {"task": task, "messages": messages}


@router.post("/api/task/{task_id}/output")
def append_output(task_id: int, body: OutputIn):
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    store.append_message(task_id, body.role, body.content, body.source)
    return {"ok": True}
```

**Step 4: Wire router into app**

```python
from src.crewai_enterprise.server import task_service

app.include_router(task_service.router)
```

**Step 5: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_service.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/crewai_enterprise/server/task_service.py src/crewai_enterprise/server/wecom_callback.py tests/server/test_task_service.py
git commit -m "feat: add task service API"
```

---

### Task 5: Task Web UI + file listing

**Files:**
- Create: `src/crewai_enterprise/server/task_viewer.py`
- Modify: `src/crewai_enterprise/server/wecom_callback.py`
- Test: `tests/server/test_task_viewer.py`

**Step 1: Write the failing test**

Note: v1 only lists/downloads files already on disk. File write API is v1.5 optional.

```python
from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app


def test_task_page_exists():
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/task/1")
    assert res.status_code == 200
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_viewer.py -v`
Expected: FAIL with 404 (route missing)

**Step 3: Write minimal implementation**

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
from src.crewai_enterprise.server.task_config import get_task_config

router = APIRouter()


@router.get("/task/{task_id}", response_class=HTMLResponse)
def task_page(task_id: int):
    return HTMLResponse("<html><body><div id='app'>Loading...</div></body></html>")


@router.get("/api/task/{task_id}/files")
def list_task_files(task_id: int):
    cfg = get_task_config()
    files_dir = os.path.join(cfg.storage_root, f"task-{task_id}", "files")
    if not os.path.isdir(files_dir):
        return {"files": []}
    return {"files": sorted(os.listdir(files_dir))}


@router.get("/api/task/{task_id}/files/{filename}")
def download_task_file(task_id: int, filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    cfg = get_task_config()
    path = os.path.join(cfg.storage_root, f"task-{task_id}", "files", filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
```

**Step 4: Wire router into app**

```python
from src.crewai_enterprise.server import task_viewer

app.include_router(task_viewer.router)
```

**Step 5: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_viewer.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/crewai_enterprise/server/task_viewer.py src/crewai_enterprise/server/wecom_callback.py tests/server/test_task_viewer.py
git commit -m "feat: add task web UI"
```

---

### Task 6: OpenCode storage reader

**Files:**
- Create: `src/crewai_enterprise/server/opencode_storage_reader.py`
- Test: `tests/server/test_opencode_storage_reader.py`

**Step 1: Write the failing test**

```python
import json
from src.crewai_enterprise.server.opencode_storage_reader import read_new_messages


def test_read_new_messages(tmp_path):
    msg_dir = tmp_path / "message" / "sess1"
    part_dir = tmp_path / "part" / "msg1"
    part_dir2 = tmp_path / "part" / "msg2"
    msg_dir.mkdir(parents=True)
    part_dir.mkdir(parents=True)
    part_dir2.mkdir(parents=True)
    (msg_dir / "msg1.json").write_text(
        json.dumps({"role": "assistant", "id": "msg1"})
    )
    (msg_dir / "msg2.json").write_text(
        json.dumps({"role": "assistant", "id": "msg2"})
    )
    (part_dir / "p1.json").write_text(json.dumps({"type": "text", "text": "hello"}))
    (part_dir2 / "p1.json").write_text(json.dumps({"type": "text", "text": "world"}))
    chunks = read_new_messages("sess1", "msg1.json", str(tmp_path))
    assert chunks[0]["text"] == "world"
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_opencode_storage_reader.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write minimal implementation**

```python
import json
import os


def read_new_messages(session_id: str, last_seen_file: str | None, storage_root: str):
    msg_root = os.path.join(storage_root, "message", session_id)
    if not os.path.isdir(msg_root):
        return []
    files = sorted(f for f in os.listdir(msg_root) if f.endswith(".json"))
    chunks = []
    for fname in files:
        path = os.path.join(msg_root, fname)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info = data.get("info", {})
        msg_id = data.get("id") or info.get("id")
        role = data.get("role") or info.get("role")
        if last_seen_file and fname <= last_seen_file:
            continue
        if role != "assistant":
            continue
        part_dir = os.path.join(storage_root, "part", msg_id)
        if not os.path.isdir(part_dir):
            continue
        text = ""
        for pfile in sorted(os.listdir(part_dir)):
            with open(os.path.join(part_dir, pfile), "r", encoding="utf-8") as pf:
                p = json.load(pf)
            if p.get("type") == "text":
                text += p.get("text", "")
        if text:
            chunks.append({"message_id": msg_id, "text": text, "filename": fname})
    return chunks
```

**Step 4: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_opencode_storage_reader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/opencode_storage_reader.py tests/server/test_opencode_storage_reader.py
git commit -m "feat: add opencode storage reader"
```

---

### Task 7: Task worker loop + CLI

**Files:**
- Create: `src/crewai_enterprise/server/task_worker.py`
- Create: `scripts/task_worker.py`
- Modify: `src/crewai_enterprise/server/opencode_client.py`
- Test: `tests/server/test_task_worker.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.server.task_worker import TaskWorker


def test_worker_no_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    worker = TaskWorker()
    assert worker.run_once() is False
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_worker.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write minimal implementation**

```python
import os
import time
from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.opencode_client import OpenCodeClient
from src.crewai_enterprise.server.opencode_storage_reader import read_new_messages


class TaskWorker:
    def __init__(self):
        cfg = get_task_config()
        self.cfg = cfg
        self.store = TaskStore(cfg.db_path)
        opencode_url = os.getenv("OPENCODE_URL", "http://localhost:4096")
        self.client = OpenCodeClient(opencode_url)

    def run_once(self) -> bool:
        self.store.init_schema()
        inp = self.store.claim_next_input()
        if not inp:
            return False
        task_id = inp["task_id"]
        task = self.store.get_task(task_id)
        last_seen_file = task.get("last_seen_message_file") if task else None
        session_id = self.store.ensure_session(task_id, self.client)
        try:
            self.client.prompt_interactive(
                session_id,
                [{"type": "text", "text": inp["content"]}],
                None,
            )
        except Exception:
            replay = self.store.list_recent_messages(task_id, limit=50)
            replay_text = "\n".join(
                f"{m['role']}: {m['content']}" for m in replay
            )
            session_id = self.client.create_session()
            self.client.prompt_interactive(
                session_id,
                [{"type": "text", "text": replay_text + "\n" + inp["content"]}],
                None,
            )

        quiet_rounds = 0
        while quiet_rounds < 3:
            chunks = read_new_messages(
                session_id,
                last_seen_file,
                self.cfg.opencode_storage_root,
            )
            if not chunks:
                quiet_rounds += 1
                time.sleep(1)
                continue
            quiet_rounds = 0
            for chunk in chunks:
                self.store.append_message(task_id, "assistant", chunk["text"], "opencode")
                self.store.update_last_seen_file(task_id, chunk["filename"])
                last_seen_file = chunk["filename"]
        self.store.mark_input_done(inp["id"])
        self.store.mark_task_done_if_idle(task_id)
        return True
```

Update OpenCodeClient to allow omitting messageID:

```python
def prompt_interactive(
    self,
    session_id: str,
    parts: List[Dict[str, Any]],
    message_id: Optional[str],
    directory: Optional[str] = None,
):
    url = f"{self.base_url}/session/{session_id}/message"
    body = {
        "noReply": False,
        "parts": parts,
        "agent": "sisyphus",
    }
    if message_id:
        body["messageID"] = message_id
    params = {"directory": directory} if directory else None
    response = self.retry_session.post(url, json=body, params=params, timeout=60)
    response.raise_for_status()
    return response
```

**Step 4: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_worker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/crewai_enterprise/server/task_worker.py scripts/task_worker.py tests/server/test_task_worker.py
git commit -m "feat: add task worker loop"
```

---

### Task 8: Wire /task into WeCom callback

**Files:**
- Create: `src/crewai_enterprise/server/handlers/task_handler.py`
- Modify: `src/crewai_enterprise/server/wecom_callback.py`
- Test: `tests/server/test_task_handler.py`

**Step 1: Write the failing test**

```python
from src.crewai_enterprise.server.handlers.task_handler import handle_task_command


def test_handle_task_create(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    res = handle_task_command("/task do something", chat_id="room", user_id="u1")
    assert "http://tasks/task/" in res


def test_handle_task_append_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    res = handle_task_command("/task 1234", chat_id="room", user_id="u1")
    assert "请输入追加内容" in res
```

**Step 2: Run test to verify it fails**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_handler.py -v`
Expected: FAIL with `ImportError`

**Step 3: Write minimal implementation**

```python
from src.crewai_enterprise.server.handlers.task_commands import parse_task_command
from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore


def handle_task_command(text: str, chat_id: str, user_id: str) -> str | None:
    cmd = parse_task_command(text)
    if not cmd:
        return None
    cfg = get_task_config()
    store = TaskStore(cfg.db_path)
    store.init_schema()
    if cmd["type"] == "create":
        task_id = store.create_task(chat_id, user_id, cmd["text"][:60])
        store.append_message(task_id, "user", cmd["text"], "wecom")
        store.append_input(task_id, cmd["text"], "wecom")
        return f"已创建任务 #{task_id} 查看进度: {cfg.base_url}/task/{task_id}"
    task_id = cmd["task_id"]
    if not cmd["text"].strip():
        return "请输入追加内容，格式：/task <任务ID> <内容>"
    store.append_message(task_id, "user", cmd["text"], "wecom")
    store.append_input(task_id, cmd["text"], "wecom")
    return f"已追加到任务 #{task_id} 查看进度: {cfg.base_url}/task/{task_id}"
```

**Step 4: Wire handler in callback**

```python
from src.crewai_enterprise.server.handlers.task_handler import handle_task_command
from src.crewai_enterprise.tools.wecom.wecom_webhook_tool import send_webhook_message

task_reply = handle_task_command(content, chat_id, user_id)
if task_reply:
    send_webhook_message(webhook_url, task_reply, msg_type="text")
    return {"status": "task_created", "chat_id": chat_id}
```

**Step 5: Run test to verify it passes**

Run (Kamatera VM): `/opt/wecom-callback/venv/bin/pytest tests/server/test_task_handler.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/crewai_enterprise/server/handlers/task_handler.py src/crewai_enterprise/server/wecom_callback.py tests/server/test_task_handler.py
git commit -m "feat: handle /task in wecom callback"
```

---

### Task 9: Documentation + service wiring (VM)

**Files:**
- Modify: `company_docs/wecom_task_link_design.md`
- Modify: `wecom-callback.service` (optional)

**Step 1: Write doc update**

```markdown
- Add env keys: TASK_BASE_URL, TASK_STORAGE_ROOT, TASK_DB_PATH, OPENCODE_STORAGE_ROOT
- Add worker start command: /opt/wecom-callback/venv/bin/python scripts/task_worker.py
- Note: file write API remains v1.5 optional (not required for v1)
```

**Step 2: Run docs lint (if any)**

Run: `git status`
Expected: only docs/service files changed

**Step 3: Commit**

```bash
git add company_docs/wecom_task_link_design.md wecom-callback.service
git commit -m "docs: document task worker setup"
```

---

## Notes for execution

- **Tests must run on Kamatera VM**: use `/opt/wecom-callback/venv/bin/pytest ...`.
- Use `TASK_STORAGE_ROOT` and `TASK_DB_PATH` pointing to `/var/lib/wecom-tasks`.
- Worker runs separately from the FastAPI app (systemd or tmux). Ensure only one worker process at a time.
