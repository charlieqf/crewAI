import os
import json
import os
import time
from datetime import datetime, timedelta, timezone

from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.opencode_client import OpenCodeClient
from src.crewai_enterprise.server.opencode_storage_reader import read_new_messages
from src.crewai_enterprise.server.opencode_file_sync import mirror_session_files
from src.crewai_enterprise.utils.wecom_context import (
    build_context_summary,
    fetch_wecom_chat_context,
)


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
        context_block = None
        if chat_id and inp.get("context_window"):
            window = int(inp["context_window"])
            end_dt = datetime.now(timezone(timedelta(hours=8)))
            start_dt = end_dt - timedelta(seconds=window)
            start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")
            try:
                messages, truncated = fetch_wecom_chat_context(
                    chat_id,
                    start_str,
                    end_str,
                )
            except Exception as exc:
                err_text = f"WeCom context failed: {exc}"
                self._write_worker_log(task_id, chat_id, err_text)
                self.store.append_message(
                    task_id,
                    "system",
                    err_text,
                    "wecom_context",
                    input_id=inp["id"],
                )
                self.store.mark_input_done(inp["id"])
                self.store.mark_task_done_if_idle(task_id)
                return True
            summary = build_context_summary(
                messages, start_str, end_str, truncated=truncated
            )
            base_dir = os.path.join(
                self.cfg.storage_root, chat_id, "tasks", str(task_id)
            )
            context_dir = os.path.join(base_dir, "files", "context")
            os.makedirs(context_dir, exist_ok=True)
            filename = f"wecom-{end_dt.strftime('%Y%m%d%H%M%S')}.json"
            file_path = os.path.join(context_dir, filename)
            if messages:
                with open(file_path, "w", encoding="utf-8") as handle:
                    json.dump(messages, handle, ensure_ascii=False, indent=2)
            download_hint = (
                f"/api/task/{task_id}/file?path=context/{filename}" if messages else ""
            )
            summary_lines = [
                "WeCom context window applied.",
                f"Timeframe: {summary['start']} to {summary['end']}",
                f"Messages: {summary['count']}",
            ]
            if summary.get("truncated"):
                summary_lines.append("Truncated: yes")
            if summary.get("first"):
                summary_lines.append(f"First: {summary['first']}")
            if summary.get("last"):
                summary_lines.append(f"Last: {summary['last']}")
            if download_hint:
                summary_lines.append(f"Context file: {download_hint}")
            summary_text = "\n".join(summary_lines)
            self.store.append_message(
                task_id,
                "system",
                summary_text,
                "wecom_context",
                input_id=inp["id"],
            )
            context_block = (
                "SYSTEM CONTEXT (WeCom)\n"
                f"Timeframe: {summary['start']} to {summary['end']}\n"
                f"Messages: {summary['count']}\n"
            )
            if summary.get("first"):
                context_block += f"First: {summary['first']}\n"
            if summary.get("last"):
                context_block += f"Last: {summary['last']}\n"
            if summary.get("truncated"):
                context_block += "Truncated: yes\n"
            context_block += "Use this context for background only.\n"
        session_id = self.store.ensure_session(task_id, self.client, workdir)
        self._write_worker_log(task_id, chat_id, f"session {session_id} ready")
        skills = _load_task_skills()
        prompt_text = _build_prompt(skills, inp.get("content", ""))
        if context_block:
            prompt_text = context_block + "\n\n" + prompt_text
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


def _load_task_skills() -> list[tuple[str, str]]:
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
