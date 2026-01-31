import os

import os

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
    workdir = os.path.join(cfg.workdir_root, str(task_id))
    os.makedirs(workdir, exist_ok=True)
    store.set_workdir(task_id, workdir)
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
