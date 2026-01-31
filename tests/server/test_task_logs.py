from pathlib import Path

from fastapi.testclient import TestClient

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_project_root))

from src.crewai_enterprise.server import task_viewer
from src.crewai_enterprise.server.wecom_callback import app


def test_task_logs_endpoint(monkeypatch):
    def fake_reader():
        return ["line 1", "line 2"]

    monkeypatch.setattr(task_viewer, "_read_worker_logs", fake_reader)
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/api/task/1/logs")
    assert res.status_code == 200
    assert res.json() == {"lines": ["line 1", "line 2"]}
