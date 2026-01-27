import json
import os
import uuid
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Maps WeCom chat_id to OpenCode session UUIDs.
    Persists mapping to a JSON file.
    """

    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self.sessions = self._load()

    def _load(self) -> Dict[str, str]:
        if os.path.exists(self.storage_path):
            try:
                lock_path = self.storage_path + ".lock"
                with open(lock_path, "a+") as lock_f:
                    try:
                        import fcntl

                        fcntl.flock(lock_f, fcntl.LOCK_SH)
                    except (ImportError, AttributeError):
                        pass

                    with open(self.storage_path, "r") as f:
                        data = json.load(f)

                    try:
                        import fcntl

                        fcntl.flock(lock_f, fcntl.LOCK_UN)
                    except (ImportError, AttributeError):
                        pass
                    return data
            except Exception as e:
                logger.error(f"Failed to load session store: {e}")
                return {}
        return {}

    def _save(self):
        try:
            lock_path = self.storage_path + ".lock"
            temp_path = self.storage_path + ".tmp"

            # Simple atomic write: Write to temp and rename
            # Using a lock file for safe concurrent access
            with open(lock_path, "a+") as lock_f:
                try:
                    import fcntl

                    fcntl.flock(lock_f, fcntl.LOCK_EX)
                except (ImportError, AttributeError):
                    pass  # Fallback for non-POSIX

                with open(temp_path, "w") as f:
                    json.dump(self.sessions, f)
                os.replace(temp_path, self.storage_path)

                try:
                    import fcntl

                    fcntl.flock(lock_f, fcntl.LOCK_UN)
                except (ImportError, AttributeError):
                    pass
        except Exception as e:
            logger.error(f"Failed to save session store: {e}")

    def get_session_id(self, chat_id: str) -> str:
        """Get or create a session UUID for a chat_id."""
        if chat_id not in self.sessions:
            self.sessions[chat_id] = self._normalize_session_id(str(uuid.uuid4()))
            self._save()
        else:
            normalized = self._normalize_session_id(self.sessions[chat_id])
            if normalized != self.sessions[chat_id]:
                self.sessions[chat_id] = normalized
                self._save()
        return self.sessions[chat_id]

    def rotate_session(self, chat_id: str) -> str:
        """Force a new session UUID for a chat_id (reset)."""
        new_id = self._normalize_session_id(str(uuid.uuid4()))
        self.sessions[chat_id] = new_id
        self._save()
        return new_id

    def _normalize_session_id(self, session_id: str) -> str:
        if session_id.startswith("ses"):
            return session_id
        return f"ses_{session_id}"
