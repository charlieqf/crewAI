import sys
import sys
from pathlib import Path

from fastapi.testclient import TestClient

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.wecom_callback import app


def test_task_list_page_exists():
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/tasks")
    assert res.status_code == 200
    assert "/api/tasks" in res.text


def test_task_list_api_returns_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    store = TaskStore(str(tmp_path / "tasks.db"))
    store.init_schema()
    task_id = store.create_task("room-1", "u1", "title")
    store.append_message(task_id, "user", "hello task", "wecom")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/tasks")
    assert res.status_code == 200
    data = res.json()
    assert data[0]["id"] == task_id
    assert data[0]["wecom_chat_id"] == "room-1"
    assert data[0]["first_prompt"] == "hello task"
