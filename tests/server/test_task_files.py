import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi.testclient import TestClient

from src.crewai_enterprise.server.task_store import TaskStore
from src.crewai_enterprise.server.wecom_callback import app


def test_task_files_directory_listing_and_download(tmp_path, monkeypatch):
    storage_root = tmp_path / "storage"
    db_path = tmp_path / "tasks.db"
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("TASK_DB_PATH", str(db_path))

    store = TaskStore(str(db_path))
    store.init_schema()
    task_id = store.create_task("room1", "user1", "title")

    files_dir = storage_root / "room1" / "tasks" / str(task_id) / "files"
    docs_dir = files_dir / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "readme.txt").write_text("hello", encoding="utf-8")
    (files_dir / "top.txt").write_text("root", encoding="utf-8")

    client = TestClient(app, raise_server_exceptions=False)

    res = client.get(f"/api/task/{task_id}/files")
    assert res.status_code == 200
    payload = res.json()
    names = [f["name"] for f in payload["files"]]
    assert "docs" in names
    assert "top.txt" in names

    res2 = client.get(f"/api/task/{task_id}/files?path=docs")
    assert res2.status_code == 200
    payload2 = res2.json()
    names2 = [f["name"] for f in payload2["files"]]
    assert "readme.txt" in names2

    res3 = client.get(f"/api/task/{task_id}/files/download?path=docs/readme.txt")
    assert res3.status_code == 200
    assert res3.text == "hello"
