import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app


def test_task_page_exists():
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/task/1")
    assert res.status_code == 200
