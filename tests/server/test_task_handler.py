from src.crewai_enterprise.server.handlers.task_handler import handle_task_command
from src.crewai_enterprise.server.task_store import TaskStore


def test_handle_task_create(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    res = handle_task_command("/task do something", chat_id="room", user_id="u1")
    assert res is not None
    assert "http://tasks/task/" in res


def test_handle_task_append_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    res = handle_task_command("/task 1234", chat_id="room", user_id="u1")
    assert res is not None
    assert "请输入追加内容" in res


def test_handle_task_create_makes_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    res = handle_task_command("/task build page", chat_id="room-a", user_id="u1")
    assert res is not None
    task_id = int(res.split("#")[1].split()[0])
    files_dir = tmp_path / "room-a" / "tasks" / str(task_id) / "files"
    assert files_dir.is_dir()


def test_handle_task_create_sets_workdir(monkeypatch, tmp_path):
    db_path = tmp_path / "tasks.db"
    workdir_root = tmp_path / "workdir"
    monkeypatch.setenv("TASK_DB_PATH", str(db_path))
    monkeypatch.setenv("TASK_BASE_URL", "http://tasks")
    monkeypatch.setenv("TASK_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("TASK_WORKDIR_ROOT", str(workdir_root))

    res = handle_task_command("/task isolate files", chat_id="room-b", user_id="u2")
    assert res is not None
    task_id = int(res.split("#")[1].split()[0])

    store = TaskStore(str(db_path))
    store.init_schema()
    task = store.get_task(task_id)
    assert task is not None
    expected = workdir_root / str(task_id)
    assert task["workdir"] == str(expected)
    assert expected.is_dir()
