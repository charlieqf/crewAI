import os
import os
import time
import re

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
        skills = _load_task_skills(inp.get("content", ""))
        prompt_text = _build_prompt(skills, inp.get("content", ""))
        try:
            self.client.prompt_interactive(
                session_id,
                [{"type": "text", "text": prompt_text}],
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
                [
                    {
                        "type": "text",
                        "text": _build_prompt(
                            skills,
                            replay_text + "\n" + inp.get("content", ""),
                        ),
                    }
                ],
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
            else:
                if _assistant_claimed_file_save(task_id, self.store):
                    warn = (
                        "I couldn't find the file you said you saved. "
                        "Please verify the file was actually written to the task workdir."
                    )
                    self.store.append_message(
                        task_id,
                        "assistant",
                        warn,
                        "system",
                        input_id=inp["id"],
                    )
                    try:
                        self.client.prompt_interactive(
                            session_id,
                            [{"type": "text", "text": warn}],
                            None,
                            directory=workdir,
                        )
                        self._write_worker_log(
                            task_id, chat_id, "warned opencode: missing file"
                        )
                    except Exception:
                        self._write_worker_log(
                            task_id, chat_id, "failed to warn opencode"
                        )
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


def _should_load_save_skill(prompt: str) -> bool:
    if os.getenv("TASK_FORCE_SAVE_SKILL") in {"1", "true", "yes", "on"}:
        return True
    text = (prompt or "").lower()
    keywords = (
        "save to ",
        "write to ",
        "write into ",
        "create file",
        "create a file",
        "generate file",
        "generate a file",
        "output to ",
        "export to ",
        "save as ",
        "保存",
        "写入",
        "写到",
        "生成文件",
        "导出",
        "输出到",
        "另存为",
        ".txt",
        ".md",
        ".html",
        ".json",
        ".csv",
        "file ",
    )
    return any(k in text for k in keywords)


def _load_task_skills(prompt: str) -> list[tuple[str, str]]:
    paths = []
    explicit_paths = os.getenv("TASK_SKILL_PATHS")
    if explicit_paths:
        paths.extend([p.strip() for p in explicit_paths.split(",") if p.strip()])
    legacy_path = os.getenv("TASK_SKILL_PATH")
    if legacy_path:
        paths.append(legacy_path.strip())
    if not paths:
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        paths.append(
            os.path.join(base_dir, "opencode_skills", "save-to-workdir", "SKILL.md")
        )

    if not _should_load_save_skill(prompt):
        paths = [p for p in paths if "save-to-workdir" not in p]

    loaded: list[tuple[str, str]] = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            continue
        name, body = _parse_skill_content(path, content)
        if body:
            loaded.append((name, body))
    return loaded


def _parse_skill_content(path: str, content: str) -> tuple[str, str]:
    name = os.path.splitext(os.path.basename(path))[0]
    body = content.strip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
            for line in frontmatter.splitlines():
                if line.strip().startswith("name:"):
                    name = line.split(":", 1)[1].strip() or name
                    break
            body = parts[2].lstrip()
    return name, body.strip()


def _build_prompt(skills: list[tuple[str, str]], prompt: str) -> str:
    prompt = prompt.strip()
    if not skills:
        return prompt
    skill_names = ", ".join(name for name, _ in skills)
    skill_blocks = "\n\n".join(body for _, body in skills if body)
    return f"Loaded skills: {skill_names}\n\n{skill_blocks}\n\nUser request:\n{prompt}".strip()


def _assistant_claimed_file_save(task_id: int, store: TaskStore) -> bool:
    messages = store.list_recent_messages(task_id, limit=10)
    if not messages:
        return False
    content = "\n".join(
        m.get("content", "") for m in messages if m.get("role") == "assistant"
    )
    if not content:
        return False
    if "Using skill: save-to-workdir" in content:
        return True
    patterns = [
        r"\b(saved|written|saved to|write to|wrote to)\b",
        r"已将|已写入|已保存|已生成",
        r"\b[\w.-]+\.(txt|md|html|json|csv)\b",
    ]
    return any(re.search(p, content, re.IGNORECASE) for p in patterns)
