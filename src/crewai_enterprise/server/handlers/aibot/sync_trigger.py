from __future__ import annotations

import os
import subprocess
import time

ARCHIVE_SYNC_LOCK = os.getenv("ARCHIVE_SYNC_LOCK", "/var/lib/wecom-callback/archive_sync.lock")
ARCHIVE_WORKER = "/opt/wecom-callback/scripts/archive_sync_worker.py"
PYTHON_BIN = "/opt/wecom-callback/venv/bin/python"


class ArchiveSyncError(Exception):
    """Fail-fast error for one-shot archive sync."""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_matches_worker(pid: int) -> bool:
    cmdline_path = f"/proc/{pid}/cmdline"
    try:
        with open(cmdline_path, "rb") as handle:
            raw = handle.read().decode("utf-8", errors="ignore")
        return "archive_sync_worker.py" in raw
    except Exception:
        return False


def trigger_archive_sync(*, reason: str, lock_ttl_secs: int = 900) -> str:
    """
    Trigger a one-shot archive sync (non-blocking).

    Raises ArchiveSyncError on lock contention or missing binaries.
    Returns a short status string if started.
    """
    _ensure_worker_exists()

    if os.path.exists(ARCHIVE_SYNC_LOCK):
        pid = None
        try:
            with open(ARCHIVE_SYNC_LOCK, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
            if raw.isdigit():
                pid = int(raw)
        except Exception:
            pid = None

        if pid and _pid_alive(pid):
            if _pid_matches_worker(pid):
                raise ArchiveSyncError(f"archive sync already running (pid={pid})")
            pid = None

        if pid is None:
            try:
                mtime = os.path.getmtime(ARCHIVE_SYNC_LOCK)
                age = time.time() - mtime
            except Exception:
                age = 0

            if age < lock_ttl_secs:
                raise ArchiveSyncError("archive sync already running (lock active)")

        # Stale lock: remove and proceed
        try:
            os.remove(ARCHIVE_SYNC_LOCK)
        except Exception as e:
            raise ArchiveSyncError(f"failed to clear stale lock: {e}") from e

    # Start worker in background
    try:
        subprocess.Popen(
            [PYTHON_BIN, ARCHIVE_WORKER, "0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        raise ArchiveSyncError(f"failed to start archive sync: {e}") from e

    return f"started (reason={reason})"


def _ensure_worker_exists() -> None:
    if not os.path.exists(PYTHON_BIN):
        raise ArchiveSyncError(f"python not found: {PYTHON_BIN}")
    if not os.path.exists(ARCHIVE_WORKER):
        raise ArchiveSyncError(f"archive worker not found: {ARCHIVE_WORKER}")
