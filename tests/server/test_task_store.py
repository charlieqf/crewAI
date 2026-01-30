import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.crewai_enterprise.server.task_store import TaskStore


def test_task_store_crud(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(str(db_path))
    store.init_schema()

    task_id = store.create_task(
        wecom_chat_id="room1",
        wecom_user_id="user1",
        title="hello",
    )
    store.append_message(task_id, role="user", content="q1", source="wecom")
    store.append_input(task_id, content="q1", source="wecom")

    inp = store.claim_next_input()
    assert inp["task_id"] == task_id
    store.mark_input_done(inp["id"])

    task = store.get_task(task_id)
    assert task["id"] == task_id
    messages = store.list_messages(task_id)
    assert messages[-1]["content"] == "q1"
