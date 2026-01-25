from __future__ import annotations

import os
import subprocess
import time

ARCHIVE_SYNC_LOCK = os.getenv("ARCHIVE_SYNC_LOCK", "/var/lib/wecom-callback/archive_sync.lock")
ARCHIVE_WORKER = "/opt/wecom-callback/scripts/archive_sync_worker.py"
PYTHON_BIN = "/opt/wecom-callback/venv/bin/python"


class ArchiveSyncError(Exception):
    """Fail-fast error for one-shot archive sync."""


def trigger_archive_sync(*, reason: str, lock_ttl_secs: int = 900) -> str:
    """
    Trigger a one-shot archive sync (non-blocking).

    Raises ArchiveSyncError on lock contention or missing binaries.
    Returns a short status string if started.
    """
    _ensure_worker_exists()

    if os.path.exists(ARCHIVE_SYNC_LOCK):
        # Lock exists: check staleness
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
