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
            replay_text = "\n".join(f"{m['role']}: {m['content']}" for m in replay)
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
                self.store.append_message(
                    task_id, "assistant", chunk["text"], "opencode"
                )
                self.store.update_last_seen_file(task_id, chunk["filename"])
                last_seen_file = chunk["filename"]
        self.store.mark_input_done(inp["id"])
        if task and task.get("wecom_chat_id"):
            chat_id = task["wecom_chat_id"]
            base_dir = os.path.join(
                self.cfg.storage_root, chat_id, "tasks", str(task_id)
            )
            files_dir = os.path.join(base_dir, "files")
            state_path = os.path.join(base_dir, "sync.json")
            mirror_session_files(
                session_id,
                files_dir,
                self.cfg.opencode_storage_root,
                state_path,
            )
        self.store.mark_task_done_if_idle(task_id)
        return True
