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
                    workdir TEXT,
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
                    input_id INTEGER,
                    user_id TEXT,
                    FOREIGN KEY (task_id) REFERENCES task(id)
                );
                CREATE TABLE IF NOT EXISTS task_input (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'pending',
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    context_source TEXT,
                    context_window INTEGER,
                    FOREIGN KEY (task_id) REFERENCES task(id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_input_task_status
                ON task_input(task_id, status, created_at);
                CREATE INDEX IF NOT EXISTS idx_task_message_task_time
                ON task_message(task_id, created_at);
                """
            )
            self._ensure_task_columns(conn)
            self._ensure_task_message_columns(conn)
            self._ensure_task_input_columns(conn)

    @staticmethod
    def _ensure_task_columns(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(task)").fetchall()}
        if "workdir" not in cols:
            conn.execute("ALTER TABLE task ADD COLUMN workdir TEXT")

    @staticmethod
    def _ensure_task_message_columns(conn: sqlite3.Connection) -> None:
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(task_message)").fetchall()
        }
        if "input_id" not in cols:
            conn.execute("ALTER TABLE task_message ADD COLUMN input_id INTEGER")
        if "user_id" not in cols:
            conn.execute("ALTER TABLE task_message ADD COLUMN user_id TEXT")

    @staticmethod
    def _ensure_task_input_columns(conn: sqlite3.Connection) -> None:
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(task_input)").fetchall()
        }
        if "context_source" not in cols:
            conn.execute("ALTER TABLE task_input ADD COLUMN context_source TEXT")
        if "context_window" not in cols:
            conn.execute("ALTER TABLE task_input ADD COLUMN context_window INTEGER")

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
        self,
        task_id: int,
        role: str,
        content: str,
        source: str,
        input_id: int | None = None,
        user_id: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO task_message(task_id, role, content, source, input_id, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, role, content, source, input_id, user_id),
            )
            conn.execute(
                "UPDATE task SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )

    def create_message(
        self,
        task_id: int,
        role: str,
        content: str,
        source: str,
        input_id: int | None = None,
        user_id: str | None = None,
    ) -> int:
        """Insert a task_message row and return its id.

        Used for streaming-style updates where the content may be updated later.
        """
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_message(task_id, role, content, source, input_id, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, role, content, source, input_id, user_id),
            )
            conn.execute(
                "UPDATE task SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
            last_id = cur.lastrowid
            if last_id is None:
                raise ValueError("Failed to create task message")
            return int(last_id)

    def update_message_content(self, message_id: int, content: str) -> None:
        """Update an existing task_message content by id."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT task_id FROM task_message WHERE id=?",
                (message_id,),
            ).fetchone()
            if not row:
                return
            task_id = int(row[0])
            conn.execute(
                "UPDATE task_message SET content=? WHERE id=?",
                (content, message_id),
            )
            conn.execute(
                "UPDATE task SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )

    def append_input(
        self,
        task_id: int,
        content: str,
        source: str,
        context_source: str | None = None,
        context_window: int | None = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_input(
                    task_id,
                    content,
                    source,
                    context_source,
                    context_window
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, content, source, context_source, context_window),
            )
            conn.execute(
                "UPDATE task SET status='queued', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,),
            )
            last_id = cur.lastrowid
            if last_id is None:
                raise ValueError("Failed to append input")
            assert last_id is not None
            return int(last_id)

    def get_input(self, input_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_input WHERE id=?",
                (input_id,),
            ).fetchone()
        return dict(row) if row else None

    def set_workdir(self, task_id: int, workdir: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE task SET workdir=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (workdir, task_id),
            )

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

    def ensure_session(
        self,
        task_id: int,
        client: OpenCodeClient,
        workdir: str | None = None,
    ) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT opencode_session_id, workdir FROM task WHERE id=?",
                (task_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
            resolved_workdir = workdir or (row[1] if row and row[1] else None)
            session_id = client.create_session(directory=resolved_workdir)
            conn.execute(
                "UPDATE task SET opencode_session_id=?, status='running' WHERE id=?",
                (session_id, task_id),
            )
            return session_id

    def list_messages(self, task_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT tm.*, ti.status AS input_status
                FROM task_message tm
                LEFT JOIN task_input ti ON ti.id = tm.input_id
                WHERE tm.task_id=?
                ORDER BY tm.created_at ASC, tm.id ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_recent_messages(
        self, task_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT tm.*, ti.status AS input_status
                FROM task_message tm
                LEFT JOIN task_input ti ON ti.id = tm.input_id
                WHERE tm.task_id=?
                ORDER BY tm.created_at DESC, tm.id DESC
                LIMIT ?
                """,
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
                """
                SELECT
                    t.*,
                    (
                        SELECT tm.content
                        FROM task_message tm
                        WHERE tm.task_id = t.id
                          AND tm.role = 'user'
                          AND tm.source = 'wecom'
                        ORDER BY tm.created_at ASC, tm.id ASC
                        LIMIT 1
                    ) AS first_prompt
                FROM task t
                ORDER BY t.updated_at DESC, t.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
