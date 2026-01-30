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
            last_id = cur.lastrowid
            if last_id is None:
                raise ValueError("Failed to create task")
            assert last_id is not None
            return int(last_id)

    def append_message(
        self, task_id: int, role: str, content: str, source: str
    ) -> None:
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
            last_id = cur.lastrowid
            if last_id is None:
                raise ValueError("Failed to append input")
            assert last_id is not None
            return int(last_id)

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

    def list_recent_messages(
        self, task_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
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

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task ORDER BY updated_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
