import sys
from pathlib import Path
import sys

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient
from src.crewai_enterprise.server.wecom_callback import app
from src.crewai_enterprise.server.task_store import TaskStore


def test_task_page_exists():
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/task/1")
    assert res.status_code == 200


def test_task_page_has_data_loader():
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/task/123")
    assert res.status_code == 200
    body = res.text
    assert "/api/task/123" in body
    assert "fetch(" in body


def test_task_files_use_chat_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))

    store = TaskStore(str(tmp_path / "tasks.db"))
    store.init_schema()
    task_id = store.create_task("chat-1", "u1", "title")

    files_dir = tmp_path / "chat-1" / "tasks" / str(task_id) / "files"
    files_dir.mkdir(parents=True)
    (files_dir / "hello.txt").write_text("hi", encoding="utf-8")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.get(f"/api/task/{task_id}/files")
    assert res.status_code == 200
    assert res.json() == {"files": ["hello.txt"]}


def test_task_file_download_uses_chat_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))

    store = TaskStore(str(tmp_path / "tasks.db"))
    store.init_schema()
    task_id = store.create_task("room-a", "u1", "title")

    files_dir = tmp_path / "room-a" / "tasks" / str(task_id) / "files"
    files_dir.mkdir(parents=True)
    (files_dir / "doc.md").write_text("hello", encoding="utf-8")

    client = TestClient(app, raise_server_exceptions=False)
    res = client.get(f"/api/task/{task_id}/files/doc.md")
    assert res.status_code == 200
    assert res.text == "hello"
