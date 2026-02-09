import json
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.crewai_enterprise.server.task_config import get_task_config
from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.opencode_client import OpenCodeClient

from src.crewai_enterprise.server.opencode_file_sync import mirror_session_files
from src.crewai_enterprise.utils.wecom_context import (
    build_context_summary,
    build_context_transcript,
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
            end_dt = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
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
            transcript, transcript_truncated = build_context_transcript(messages)
            summary = build_context_summary(
                messages,
                start_str,
                end_str,
                truncated=truncated or transcript_truncated,
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
            if summary.get("truncated"):
                context_block += "Truncated: yes\n"
            context_block += "TRANSCRIPT:\n"
            if transcript:
                context_block += transcript + "\n"
            context_block += "Use this context for background only.\n"
        session_id = self.store.ensure_session(task_id, self.client, workdir)
        self._write_worker_log(task_id, chat_id, f"session {session_id} ready")
        try:
            config = self.client.get_config()
            agent_cfg = config.get("agent", {}) if isinstance(config, dict) else {}
            agent_info = agent_cfg.get(self.client.default_agent or "", {})
            model_info = (
                agent_info.get("model") if isinstance(agent_info, dict) else None
            )
            self._write_worker_log(
                task_id,
                chat_id,
                f"opencode model (agent config): {model_info}",
            )
            self._write_worker_log(
                task_id,
                chat_id,
                f"opencode model (default_model): {self.client.default_model}",
            )
        except Exception as exc:
            self._write_worker_log(task_id, chat_id, f"model lookup failed: {exc}")
        skills = _load_task_skills(inp.get("content", ""))
        prompt_text = _build_prompt(skills, inp.get("content", ""))
        guard = (
            "IMPORTANT: If you claim a file was saved, it must exist on disk in the workdir. "
            "If you cannot write the file, say so clearly."
        )
        lang_guard = (
            "IMPORTANT: Reply in Chinese. Technical terms that are commonly written in English "
            "may remain in English. The only exception is a leading line like "
            "'Using skill: save-to-workdir', which may remain in English."
        )
        prompt_text = guard + "\n" + lang_guard + "\n\n" + prompt_text
        if context_block:
            prompt_text = context_block + "\n\n" + prompt_text

        def extract_text_from_message(msg: dict) -> str:
            if not isinstance(msg, dict):
                return ""
            parts = msg.get("parts", [])
            if not isinstance(parts, list):
                return ""
            chunks: list[str] = []
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        chunks.append(text)
            return "".join(chunks)

        stream_message_id: int | None = None
        last_stream_text = ""
        try:
            self._write_worker_log(task_id, chat_id, "prompt dispatch (polling)")
            for event in self.client.prompt_interactive_with_polling(
                session_id=session_id,
                parts=[{"type": "text", "text": prompt_text}],
                message_id=None,
                directory=workdir,
                poll_interval=float(os.getenv("TASK_OPENCODE_POLL_INTERVAL", "2")),
                max_wait=float(os.getenv("TASK_OPENCODE_MAX_WAIT", "280")),
            ):
                etype = event.get("type") if isinstance(event, dict) else None
                if etype in {"text", "final"}:
                    text = event.get("text")
                    if not isinstance(text, str) or not text:
                        continue
                    if text == last_stream_text:
                        continue
                    last_stream_text = text
                    if stream_message_id is None:
                        stream_message_id = self.store.create_message(
                            task_id,
                            "assistant",
                            text,
                            "opencode",
                            input_id=inp["id"],
                        )
                    else:
                        self.store.update_message_content(stream_message_id, text)
                elif etype == "complete":
                    data = event.get("data")
                    if isinstance(data, dict):
                        text = extract_text_from_message(data)
                        if text and text != last_stream_text:
                            last_stream_text = text
                            if stream_message_id is None:
                                stream_message_id = self.store.create_message(
                                    task_id,
                                    "assistant",
                                    text,
                                    "opencode",
                                    input_id=inp["id"],
                                )
                            else:
                                self.store.update_message_content(
                                    stream_message_id, text
                                )
                elif etype == "error":
                    msg = event.get("message") if isinstance(event, dict) else None
                    if isinstance(msg, str) and msg:
                        self.store.append_message(
                            task_id,
                            "assistant",
                            msg,
                            "opencode",
                            input_id=inp["id"],
                        )
                    break
                elif etype in {"tool_call", "tool_result"}:
                    # Keep task page focused on assistant output; tool events go to worker.log.
                    try:
                        name = event.get("name")
                        self._write_worker_log(
                            task_id, chat_id, f"opencode {etype}: {name}"
                        )
                    except Exception:
                        pass

            self._write_worker_log(task_id, chat_id, "prompt completed")
        except Exception:
            self._write_worker_log(task_id, chat_id, "prompt failed; replaying")
            replay = self.store.list_recent_messages(task_id, limit=50)
            replay_text = "\n".join(f"{m['role']}: {m['content']}" for m in replay)
            session_id = self.client.create_session(directory=workdir)
            self._write_worker_log(
                task_id, chat_id, f"new session {session_id} created"
            )
            self._write_worker_log(task_id, chat_id, "replay prompt dispatch (polling)")
            for event in self.client.prompt_interactive_with_polling(
                session_id=session_id,
                parts=[
                    {
                        "type": "text",
                        "text": _build_prompt(
                            skills,
                            replay_text + "\n" + inp.get("content", ""),
                        ),
                    }
                ],
                message_id=None,
                directory=workdir,
                poll_interval=float(os.getenv("TASK_OPENCODE_POLL_INTERVAL", "2")),
                max_wait=float(os.getenv("TASK_OPENCODE_MAX_WAIT", "280")),
            ):
                etype = event.get("type") if isinstance(event, dict) else None
                if etype in {"text", "final"}:
                    text = event.get("text")
                    if not isinstance(text, str) or not text:
                        continue
                    if text == last_stream_text:
                        continue
                    last_stream_text = text
                    if stream_message_id is None:
                        stream_message_id = self.store.create_message(
                            task_id,
                            "assistant",
                            text,
                            "opencode",
                            input_id=inp["id"],
                        )
                    else:
                        self.store.update_message_content(stream_message_id, text)
                elif etype == "complete":
                    data = event.get("data")
                    if isinstance(data, dict):
                        text = extract_text_from_message(data)
                        if text and text != last_stream_text:
                            last_stream_text = text
                            if stream_message_id is None:
                                stream_message_id = self.store.create_message(
                                    task_id,
                                    "assistant",
                                    text,
                                    "opencode",
                                    input_id=inp["id"],
                                )
                            else:
                                self.store.update_message_content(
                                    stream_message_id, text
                                )
                elif etype == "error":
                    msg = event.get("message") if isinstance(event, dict) else None
                    if isinstance(msg, str) and msg:
                        self.store.append_message(
                            task_id,
                            "assistant",
                            msg,
                            "opencode",
                            input_id=inp["id"],
                        )
                    break

            self._write_worker_log(task_id, chat_id, "replay prompt completed")
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
                if _assistant_claimed_file_save(
                    task_id, self.store
                ) and not _claimed_files_exist(
                    task_id,
                    self.store,
                    files_dir,
                    workdir,
                ):
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
            self._verify_claimed_files(task_id, inp["id"], files_dir, workdir)
        self.store.mark_task_done_if_idle(task_id)
        return True

    def _verify_claimed_files(
        self,
        task_id: int,
        input_id: int,
        files_dir: str,
        workdir: str | None,
    ) -> None:
        messages = self.store.list_messages(task_id)
        latest = None
        for msg in reversed(messages):
            if msg.get("input_id") == input_id and msg.get("role") == "assistant":
                latest = msg
                break
        if not latest:
            return
        text = latest.get("content") or ""
        if not re.search(r"已写入|written|saved|path", text, re.IGNORECASE):
            return
        filenames = re.findall(
            r"([A-Za-z0-9._-]+\.(?:html|md|txt|json|csv|png|jpg|jpeg|pdf))",
            text,
        )
        if not filenames:
            return
        missing = []
        for name in filenames:
            file_in_files = os.path.join(files_dir, name)
            file_in_workdir = os.path.join(workdir, name) if workdir else None
            if os.path.exists(file_in_files):
                continue
            if file_in_workdir and os.path.exists(file_in_workdir):
                continue
            missing.append(name)
        if missing:
            warning = (
                "File claim verification failed. Claimed files not found: "
                + ", ".join(missing)
            )
            self.store.append_message(
                task_id,
                "system",
                warning,
                "file_check",
                input_id=input_id,
            )

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


def _claimed_files_exist(
    task_id: int, store: TaskStore, files_dir: str, workdir: str | None
) -> bool:
    messages = store.list_recent_messages(task_id, limit=10)
    if not messages:
        return False
    content = "\n".join(
        m.get("content", "") for m in messages if m.get("role") == "assistant"
    )
    if not content:
        return False
    filenames = re.findall(
        r"([A-Za-z0-9._-]+\.(?:html|md|txt|json|csv|png|jpg|jpeg|pdf))",
        content,
    )
    if not filenames:
        return False
    for name in filenames:
        file_in_files = os.path.join(files_dir, name)
        if os.path.exists(file_in_files):
            return True
        if workdir:
            file_in_workdir = os.path.join(workdir, name)
            if os.path.exists(file_in_workdir):
                return True
    return False
