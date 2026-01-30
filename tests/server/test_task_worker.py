from src.crewai_enterprise.server.task_worker import TaskWorker


def test_worker_no_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("TASK_DB_PATH", str(tmp_path / "tasks.db"))
    worker = TaskWorker()
    assert worker.run_once() is False
