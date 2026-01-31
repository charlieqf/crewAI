import os
import os
import time

from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.opencode_client import OpenCodeClient
from src.crewai_enterprise.server.opencode_storage_reader import read_new_messages
from src.crewai_enterprise.server.opencode_file_sync import mirror_session_files


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
        chat_id = task.get("wecom_chat_id") if task else None
        last_seen_file = task.get("last_seen_message_file") if task else None
        workdir = task.get("workdir") if task else None
        self._write_worker_log(
            task_id,
            chat_id,
            f"claimed input {inp['id']} (len={len(inp.get('content', ''))})",
        )
        if workdir:
            os.makedirs(workdir, exist_ok=True)
        session_id = self.store.ensure_session(task_id, self.client, workdir)
        self._write_worker_log(task_id, chat_id, f"session {session_id} ready")
        try:
            self.client.prompt_interactive(
                session_id,
                [{"type": "text", "text": inp["content"]}],
                None,
                directory=workdir,
            )
            self._write_worker_log(task_id, chat_id, "prompt sent")
        except Exception:
            self._write_worker_log(task_id, chat_id, "prompt failed; replaying")
            replay = self.store.list_recent_messages(task_id, limit=50)
            replay_text = "\n".join(f"{m['role']}: {m['content']}" for m in replay)
            session_id = self.client.create_session(directory=workdir)
            self._write_worker_log(
                task_id, chat_id, f"new session {session_id} created"
            )
            self.client.prompt_interactive(
                session_id,
                [{"type": "text", "text": replay_text + "\n" + inp["content"]}],
                None,
                directory=workdir,
            )
            self._write_worker_log(task_id, chat_id, "replay prompt sent")

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
            self._write_worker_log(task_id, chat_id, f"received {len(chunks)} chunks")
            for chunk in chunks:
                self.store.append_message(
                    task_id,
                    "assistant",
                    chunk["text"],
                    "opencode",
                    input_id=inp["id"],
                )
                self.store.update_last_seen_file(task_id, chunk["filename"])
                last_seen_file = chunk["filename"]
        self.store.mark_input_done(inp["id"])
        self._write_worker_log(task_id, chat_id, f"input {inp['id']} done")
        if task and task.get("wecom_chat_id"):
            chat_id = task["wecom_chat_id"]
            base_dir = os.path.join(
                self.cfg.storage_root, chat_id, "tasks", str(task_id)
            )
            files_dir = os.path.join(base_dir, "files")
            state_path = os.path.join(base_dir, "sync.json")
            copied = mirror_session_files(
                session_id,
                files_dir,
                self.cfg.opencode_storage_root,
                state_path,
                workdir=workdir,
            )
            if copied:
                self._write_worker_log(task_id, chat_id, f"synced {len(copied)} files")
        self.store.mark_task_done_if_idle(task_id)
        return True

    def _write_worker_log(
        self, task_id: int, chat_id: str | None, message: str
    ) -> None:
        if not chat_id:
            return
        base_dir = os.path.join(self.cfg.storage_root, chat_id, "tasks", str(task_id))
        os.makedirs(base_dir, exist_ok=True)
        log_path = os.path.join(base_dir, "worker.log")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"[{ts}] {message}\n")
        except OSError:
            return
