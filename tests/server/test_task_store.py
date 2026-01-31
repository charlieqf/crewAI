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
    input_id = store.append_input(task_id, content="q1", source="wecom")
    store.append_message(
        task_id,
        role="user",
        content="q1",
        source="wecom",
        input_id=input_id,
        user_id="user1",
    )

    inp = store.claim_next_input()
    assert inp is not None
    assert inp["task_id"] == task_id
    store.mark_input_done(inp["id"])

    task = store.get_task(task_id)
    assert task is not None
    assert task["id"] == task_id
    messages = store.list_messages(task_id)
    assert messages[-1]["content"] == "q1"
    assert messages[-1]["input_status"] == "done"
    assert messages[-1]["user_id"] == "user1"


def test_append_input_sets_task_queued(tmp_path):
    db_path = tmp_path / "tasks.db"
    store = TaskStore(str(db_path))
    store.init_schema()

    task_id = store.create_task("room1", "user1", "title")
    store.append_input(task_id, content="first", source="wecom")
    inp = store.claim_next_input()
    assert inp is not None
    assert inp["task_id"] == task_id
    store.mark_input_done(inp["id"])

    store.append_input(task_id, content="second", source="wecom")
    task = store.get_task(task_id)
    assert task is not None
    assert task["status"] == "queued"
    inp2 = store.claim_next_input()
    assert inp2 is not None
    assert inp2["content"] == "second"
