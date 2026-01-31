import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app
from src.crewai_enterprise.server.task_store import TaskStore


def test_task_create_and_append(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    monkeypatch.setenv("TASK_WORKDIR_ROOT", str(tmp_path / "workdir"))

    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/task",
        json={"chat_id": "room1", "user_id": "u1", "text": "hello"},
    )
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    store = TaskStore(str(tmp_path / "tasks.db"))
    task = store.get_task(task_id)
    assert task is not None
    workdir = task.get("workdir")
    assert workdir is not None
    assert (tmp_path / "workdir" / str(task_id)).is_dir()
    res2 = client.post(
        f"/api/task/{task_id}/append",
        json={"chat_id": "room1", "user_id": "u1", "text": "more"},
    )
    assert res2.status_code == 200
