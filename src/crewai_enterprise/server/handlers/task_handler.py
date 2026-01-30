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
