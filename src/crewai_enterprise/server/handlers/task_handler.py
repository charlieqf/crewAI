import os
from datetime import datetime, timedelta, timezone

import os

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
        _ensure_task_dirs(cfg.storage_root, chat_id, task_id)
        workdir = os.path.join(cfg.workdir_root, str(task_id))
        _ensure_task_workdir(store, task_id, workdir)
        input_id = store.append_input(
            task_id,
            cmd["text"],
            "wecom",
            context_source="wecom" if cmd.get("context_window") else None,
            context_window=cmd.get("context_window"),
        )
        store.append_message(
            task_id,
            "user",
            cmd["text"],
            "wecom",
            input_id=input_id,
            user_id=user_id,
        )
        reply = f"已创建任务 #{task_id} 查看进度: {cfg.base_url}/task/{task_id}"
        if cmd.get("context_window"):
            end_dt = datetime.now(timezone(timedelta(hours=8)))
            start_dt = end_dt - timedelta(seconds=int(cmd["context_window"]))
            reply += (
                f"（已包含 {start_dt.strftime('%Y-%m-%d %H:%M')} 至 "
                f"{end_dt.strftime('%Y-%m-%d %H:%M')} 的聊天上下文）"
            )
        return reply
    task_id = cmd["task_id"]
    if not cmd["text"].strip():
        return "请输入追加内容，格式：/task <任务ID> <内容>"
    task = store.get_task(task_id)
    chat_folder = task.get("wecom_chat_id") if task else None
    if chat_folder:
        _ensure_task_dirs(cfg.storage_root, chat_folder, task_id)
    if task and task.get("workdir"):
        os.makedirs(task["workdir"], exist_ok=True)
    input_id = store.append_input(
        task_id,
        cmd["text"],
        "wecom",
        context_source="wecom" if cmd.get("context_window") else None,
        context_window=cmd.get("context_window"),
    )
    store.append_message(
        task_id,
        "user",
        cmd["text"],
        "wecom",
        input_id=input_id,
        user_id=user_id,
    )
    reply = f"已追加到任务 #{task_id} 查看进度: {cfg.base_url}/task/{task_id}"
    if cmd.get("context_window"):
        end_dt = datetime.now(timezone(timedelta(hours=8)))
        start_dt = end_dt - timedelta(seconds=int(cmd["context_window"]))
        reply += (
            f"（已包含 {start_dt.strftime('%Y-%m-%d %H:%M')} 至 "
            f"{end_dt.strftime('%Y-%m-%d %H:%M')} 的聊天上下文）"
        )
    return reply


def _ensure_task_dirs(storage_root: str, chat_id: str, task_id: int) -> None:
    base_dir = os.path.join(storage_root, chat_id, "tasks", str(task_id))
    files_dir = os.path.join(base_dir, "files")
    os.makedirs(files_dir, exist_ok=True)


def _ensure_task_workdir(store: TaskStore, task_id: int, workdir: str) -> None:
    os.makedirs(workdir, exist_ok=True)
    store.set_workdir(task_id, workdir)
