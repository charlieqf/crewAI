from dataclasses import dataclass
import os


@dataclass(frozen=True)
class TaskConfig:
    base_url: str
    storage_root: str
    db_path: str
    opencode_storage_root: str


def get_task_config() -> TaskConfig:
    base_url = os.getenv("TASK_BASE_URL", "http://127.0.0.1:8080")
    storage_root = os.getenv("TASK_STORAGE_ROOT", "/var/lib/wecom-tasks")
    db_path = os.getenv("TASK_DB_PATH", os.path.join(storage_root, "tasks.db"))
    opencode_storage_root = os.getenv(
        "OPENCODE_STORAGE_ROOT", "/root/.local/share/opencode/storage"
    )
    return TaskConfig(
        base_url=base_url,
        storage_root=storage_root,
        db_path=db_path,
        opencode_storage_root=opencode_storage_root,
    )
