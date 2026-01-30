import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app


def test_task_create_and_append(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.post(
        "/api/task",
        json={"chat_id": "room1", "user_id": "u1", "text": "hello"},
    )
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    res2 = client.post(
        f"/api/task/{task_id}/append",
        json={"chat_id": "room1", "user_id": "u1", "text": "more"},
    )
    assert res2.status_code == 200
