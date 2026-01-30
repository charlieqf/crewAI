import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.crewai_enterprise.server.task_config import get_task_config


def test_task_config_defaults(monkeypatch):
    monkeypatch.delenv("TASK_BASE_URL", raising=False)
    monkeypatch.delenv("TASK_STORAGE_ROOT", raising=False)
    monkeypatch.delenv("TASK_DB_PATH", raising=False)
    monkeypatch.delenv("OPENCODE_STORAGE_ROOT", raising=False)

    cfg = get_task_config()
    assert cfg.base_url
    assert cfg.storage_root
    assert cfg.db_path.endswith("tasks.db")
    assert "opencode" in cfg.opencode_storage_root
