import json
import os
import shutil
import time

IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "venv", ".venv", "__pycache__"}
IGNORED_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
}


def _find_session_file(storage_root: str, session_id: str) -> str | None:
    session_root = os.path.join(storage_root, "session")
    if not os.path.isdir(session_root):
        return None
    target = f"{session_id}.json"
    for root, _, files in os.walk(session_root):
        if target in files:
            return os.path.join(root, target)
    return None


def _load_session_directory(session_file: str) -> str | None:
    try:
        with open(session_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    directory = data.get("directory")
    if not directory or not isinstance(directory, str):
        return None
    return directory


def _read_last_sync(state_path: str) -> float:
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        value = data.get("last_sync")
        if isinstance(value, (int, float)):
            return float(value)
    except (OSError, json.JSONDecodeError):
        return 0.0
    return 0.0


def _write_last_sync(state_path: str, ts: float) -> None:
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    payload = {"last_sync": ts}
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def mirror_session_files(
    session_id: str,
    task_files_dir: str,
    storage_root: str,
    state_path: str,
) -> list[str]:
    session_file = _find_session_file(storage_root, session_id)
    if not session_file:
        return []
    repo_dir = _load_session_directory(session_file)
    if not repo_dir or not os.path.isdir(repo_dir):
        return []

    last_sync = _read_last_sync(state_path)
    os.makedirs(task_files_dir, exist_ok=True)
    copied: list[str] = []

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in files:
            if name in IGNORED_FILES:
                continue
            src = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(src)
            except OSError:
                continue
            if mtime <= last_sync:
                continue
            rel_path = os.path.relpath(src, repo_dir)
            dest = os.path.join(task_files_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(rel_path)

    _write_last_sync(state_path, time.time())
    return copied
