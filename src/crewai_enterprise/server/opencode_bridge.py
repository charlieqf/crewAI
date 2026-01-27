import logging
import os
import subprocess
import json
import time

try:
    import fcntl
except ImportError:
    fcntl = None  # Fallback for Windows/Non-POSIX
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from .opencode_client import OpenCodeClient
from .archive_reader import ArchiveReader
from .session_store import SessionStore
from .models.opencode import WeComInbound, OpenCodePart, BackfillChunk

# Beijing Timezone for alignment
BEIJING_TZ = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)


class OpenCodeBridge:
    def __init__(
        self,
        opencode_url: str,
        history_db: str,
        storage_db: str,
        api_key: Optional[str] = None,
        default_repo_path: str = "/opt/oh-my-opencode",
    ):
        from src.crewai_enterprise.utils.chat_context import ChatContextManager

        self.client = OpenCodeClient(opencode_url, api_key=api_key)
        self.archive = ArchiveReader(history_db, storage_db)
        self.hot_context = ChatContextManager(db_path=storage_db)
        self.default_repo_path = default_repo_path

        # Path to the standalone sync worker
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        default_worker = os.path.join(base_dir, "scripts", "archive_sync_worker.py")

        self.sync_worker_path = os.getenv("SYNC_WORKER_PATH", default_worker)
        self.python_path = os.getenv("SYNC_PYTHON_PATH", "python")

        # Persistence for sync state
        state_dir = os.path.dirname(history_db)
        self.state_file = os.path.join(state_dir, "opencode_sync_state.json")
        self.lock_file = os.path.join(state_dir, "opencode_sync_state.lock")
        self.sync_state = self._load_state()

        # Session mapping
        session_file = os.path.join(state_dir, "opencode_sessions.json")
        self.session_store = SessionStore(session_file)

        self.repo_mapping = {}

    def _load_state(self) -> Dict[str, Any]:
        if not fcntl:
            return {}  # Skip if fcntl not available (local windows testing)
        if os.path.exists(self.state_file):
            try:
                # Use a separate lock file for safety
                with open(self.lock_file, "a+") as lock_f:
                    fcntl.flock(lock_f, fcntl.LOCK_SH)
                    with open(self.state_file, "r") as f:
                        data = json.load(f)
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
                    return data
            except Exception:
                return {}
        return {}

    def _parse_ts(self, ts_str: str) -> datetime:
        """Robust timestamp parsing with ISO fallback."""
        try:
            return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(
                tzinfo=None
            )

    def _save_state(self):
        if not fcntl:
            return  # Skip if fcntl not available
        try:
            temp_file = self.state_file + ".tmp"
            with open(self.lock_file, "a+") as lock_f:
                fcntl.flock(lock_f, fcntl.LOCK_EX)

                with open(temp_file, "w") as tf:
                    json.dump(self.sync_state, tf)
                os.replace(temp_file, self.state_file)

                fcntl.flock(lock_f, fcntl.LOCK_UN)
        except Exception as e:
            logger.critical(
                f"[BRIDGE] FATAL: Sync state persistence failed (Check permissions on {self.state_file}): {e}"
            )
            # Surface as a critical warning that will appear in logs

    def _get_last_sync_marker(self, chat_id: str) -> tuple[str, str, int]:
        value = self.sync_state.get(chat_id)
        if isinstance(value, dict):
            ts = value.get("ts") or "1970-01-01 00:00:00"
            msg_id = value.get("msg_id") or ""
            seq = int(value.get("seq") or 0)
            return ts, msg_id, seq
        if isinstance(value, str):
            return value, "", 0
        return "1970-01-01 00:00:00", "", 0

    def _update_last_sync_time(
        self,
        chat_id: str,
        ts: str,
        msg_id: str | None = None,
        seq: int | None = None,
    ):
        current = self.sync_state.get(chat_id)
        current_msg_id = current.get("msg_id") if isinstance(current, dict) else ""
        current_seq = current.get("seq") if isinstance(current, dict) else 0
        if msg_id is None:
            msg_id = current_msg_id
        if seq is None:
            seq = int(current_seq or 0)
        self.sync_state[chat_id] = {
            "ts": ts,
            "msg_id": msg_id or "",
            "seq": int(seq or 0),
        }
        self._save_state()

    def get_chat_max_seq(self, chat_id: str) -> int:
        """Return the latest archived sequence number for a chat."""
        import sqlite3

        query = """
            SELECT COALESCE(MAX(seq), 0)
            FROM archived_messages
            WHERE room_id = ?
        """
        try:
            with sqlite3.connect(self.archive.history_db_path) as conn:
                cursor = conn.execute(query, (chat_id,))
                row = cursor.fetchone()
                return int(row[0] or 0) if row else 0
        except Exception as e:
            logger.warning(f"[BRIDGE] Failed to fetch max seq for {chat_id}: {e}")
            return 0

    def _force_archive_sync(self):
        """Trigger the archive sync worker to pull the latest messages on-demand."""
        logger.info("[BRIDGE] Triggering on-demand archive sync...")
        try:
            # We run with start_seq=0 to let it use the current DB cursor
            result = subprocess.run(
                [self.python_path, self.sync_worker_path, "0"],
                capture_output=True,
                text=True,
                timeout=15,  # Hard timeout for MVP
            )
            if result.returncode == 0:
                logger.info(f"[BRIDGE] Sync completed: {result.stdout}")
            else:
                logger.error(f"[BRIDGE] Sync worker failed: {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("[BRIDGE] Sync worker timed out after 15s")
        except Exception as e:
            logger.error(f"[BRIDGE] Failed to launch sync worker: {e}")

    def _get_directory(self, chat_id: str) -> str:
        """Get the absolute repo path for a given chat_id."""
        return self.repo_mapping.get(chat_id, self.default_repo_path)

    def _resolve_user_name(self, msg: Dict[str, Any]) -> str:
        user_name = msg.get("user_name") or msg.get("user_id") or "unknown"
        try:
            content = msg.get("content")
            if content:
                content_json = (
                    json.loads(content) if isinstance(content, str) else content
                )
                pref_name = (
                    content_json.get("from_chatroom_member_name")
                    or content_json.get("from_name")
                    or content_json.get("display_name")
                )
                if pref_name:
                    user_name = pref_name
        except Exception:
            pass
        return user_name

    def _normalize_archive_content(self, msg: Dict[str, Any]) -> str:
        content = msg.get("content") or ""
        msg_type = msg.get("msg_type") or ""
        content_json: Dict[str, Any] | None = None

        def find_text(value: Any, depth: int = 2) -> str | None:
            if depth < 0:
                return None
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for key in (
                    "content",
                    "text",
                    "msg",
                    "message",
                    "title",
                    "filename",
                    "file_name",
                    "desc",
                    "description",
                ):
                    if key in value:
                        found = find_text(value.get(key), depth - 1)
                        if found:
                            return found
                for nested in value.values():
                    found = find_text(nested, depth - 1)
                    if found:
                        return found
            if isinstance(value, list):
                for item in value:
                    found = find_text(item, depth - 1)
                    if found:
                        return found
            return None

        if isinstance(content, dict):
            content_json = content
        elif isinstance(content, str) and content.strip().startswith("{"):
            try:
                content_json = json.loads(content)
            except Exception:
                content_json = None

        text = ""
        if content_json:
            found = find_text(content_json)
            if found:
                text = found

            if not text and msg_type in ("image", "file", "voice", "video"):
                file_name = (
                    content_json.get("filename")
                    or content_json.get("file_name")
                    or content_json.get("title")
                )
                if msg_type == "image":
                    text = "[image]"
                elif msg_type == "voice":
                    text = "[voice]"
                elif msg_type == "video":
                    text = "[video]"
                else:
                    text = f"[file: {file_name}]" if file_name else "[file]"

        if not text:
            if isinstance(content, str):
                text = content.strip()
            elif content is not None:
                text = str(content)

        if not text:
            text = f"[{msg_type}]" if msg_type else "[message]"

        if len(text) > 500:
            text = f"{text[:500]}..."

        return text

    def _get_hot_context(self, chat_id: str, last_sync_ts: str) -> List[Dict[str, Any]]:
        """Fetch recent bot/human context from ChatContextManager since last sync."""
        try:
            # High Finding Fix: Use get_context().messages (get_messages doesn't exist)
            context = self.hot_context.get_context(chat_id)
            messages = context.messages

            hot_messages = []
            for msg in messages:
                # Standardize timestamp comparison: replace ISO 'T' with space if present
                msg_ts = msg.get("timestamp", "").replace("T", " ")
                if msg_ts > last_sync_ts:
                    hot_messages.append(msg)
            # Sort by sequence or time to ensure correct injection order
            hot_messages.sort(key=lambda x: x.get("timestamp", ""))
            return hot_messages
        except Exception as e:
            logger.warning(f"[BRIDGE] Failed to fetch hot context: {e}")
            return []

    async def handle_mention(self, msg: WeComInbound) -> str:
        """Deprecated sync path. Use handle_mention_stream for better UX."""
        final_text = ""
        async for event in self.handle_mention_stream(msg):
            if event.get("type") == "text":
                final_text += event.get("content", "")
        return final_text or "OpenCode response failed."

    def _build_transcript_chunks(
        self, messages: List[Dict[str, Any]]
    ) -> List[BackfillChunk]:
        """
        Aggregate messages into transcript chunks.
        Rules: count <= 100, chars <= 30k, window <= 30m.
        """
        chunks = []
        if not messages:
            return chunks

        current_msgs = []
        current_chars = 0
        chunk_start_ts = None

        for msg in messages:
            ts_dt = self._parse_ts(msg["created_at"])
            display_name = self._resolve_user_name(msg)

            if chunk_start_ts is None:
                chunk_start_ts = ts_dt

            # Estimate char count for this message in transcript format
            msg_text = self._normalize_archive_content(msg)
            line = f"[{ts_dt.strftime('%H:%M')}] {display_name}: {msg_text}"

            # Check limits
            time_diff = ts_dt - chunk_start_ts
            if (
                len(current_msgs) >= 100
                or current_chars + len(line) > 30000
                or time_diff > timedelta(minutes=30)
            ):
                # Flush current chunk
                # [FIX] Finding 5 & Refined Finding 2: Robust ISO parsing for end timestamp
                chunk_end_ts = (
                    self._parse_ts(current_msgs[-1]["created_at"])
                    if current_msgs
                    else ts_dt
                )
                chunks.append(
                    self._create_chunk(current_msgs, chunk_start_ts, chunk_end_ts)
                )
                current_msgs = []
                current_chars = 0
                chunk_start_ts = ts_dt

            current_msgs.append(msg)
            current_chars += len(line) + 1

        if current_msgs:
            chunk_end_ts = self._parse_ts(current_msgs[-1]["created_at"])
            chunks.append(
                self._create_chunk(current_msgs, chunk_start_ts, chunk_end_ts)
            )

        return chunks

    def _create_chunk(
        self, messages: List[Dict[str, Any]], start: datetime, end: datetime
    ) -> BackfillChunk:
        """Helper to format a single transcript chunk."""
        lines = [f"[Transcript Backfill]"]
        lines.append(
            f"range={start.strftime('%Y-%m-%d %H:%M')} - {end.strftime('%H:%M')}"
        )
        lines.append(f"count={len(messages)}")

        participants = sorted(list(set(self._resolve_user_name(m) for m in messages)))
        lines.append(f"participants={', '.join(participants)}")

        for m in messages:
            ts_dt = self._parse_ts(m["created_at"])
            display_name = self._resolve_user_name(m)
            text = self._normalize_archive_content(m)
            if m.get("msg_type") in ["image", "file"]:
                ocr = self.archive.fetch_ocr_content(m["msg_id"])
                if ocr:
                    text += f" [OCR: {ocr[:200]}...]"
            lines.append(f"- [{ts_dt.strftime('%H:%M')}] {display_name}: {text}")

        import uuid

        # [FIX] Finding 2: Ensure unique chunk_id even for bursty traffic
        unique_suffix = uuid.uuid4().hex[:8]

        # [FIX] Refined Finding 1: Use Beijing timezone for accurate Unix seconds
        unix_start = int(start.replace(tzinfo=BEIJING_TZ).timestamp())
        unix_end = int(end.replace(tzinfo=BEIJING_TZ).timestamp())

        return BackfillChunk(
            chunk_id=f"chunk_{unix_start}_{unique_suffix}",
            range_start=unix_start,
            range_end=unix_end,
            message_count=len(messages),
            text="\n".join(lines),
            # [FIX] Refined Finding 1: Track the exact timestamp of the last message in this chunk
            metadata={
                "last_msg_ts": messages[-1]["created_at"],
                "last_msg_id": messages[-1]["msg_id"],
                "last_msg_seq": int(messages[-1].get("seq") or 0),
            }
            if messages
            else None,
        )

    async def handle_mention_stream(self, msg: WeComInbound):
        """
        Processes a mention: Iterative Sync -> Send Prompt -> Yield SSE Events.
        """
        chat_id = msg.chat_id
        msg_id = msg.msg_id
        session_uuid = self.session_store.get_session_id(
            chat_id,
            creator=lambda: self.client.create_session(directory=directory),
        )
        directory = self._get_directory(chat_id)

        # 0. Force Archive Sync
        self._force_archive_sync()

        last_sync_ts, last_sync_msg_id, last_sync_seq = self._get_last_sync_marker(
            chat_id
        )

        # 1. Fetch DIFF from Archive (Aggregated Sync)
        while True:
            # Query for next batch of messages
            # Note: We group them first to avoid too many prompt_async calls
            query = """
                SELECT seq, msgid as msg_id, sender_id as user_name, created_at, content, msgtype as msg_type
                FROM archived_messages
                WHERE room_id = ?
                  AND seq > ?
                  AND msgid != ?
                ORDER BY seq ASC
                LIMIT 300
            """
            import sqlite3

            batch_history = []
            try:
                with sqlite3.connect(self.archive.history_db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.execute(query, (chat_id, last_sync_seq, msg_id))
                    batch_history = [dict(r) for r in cursor.fetchall()]
            except Exception as e:
                logger.error(f"[BRIDGE] Failed to fetch sync batch: {e}")
                break

            if not batch_history:
                break

            # Use the chunking algorithm for Phase 3 efficiency
            chunks = self._build_transcript_chunks(batch_history)

            # [FIX] Finding 3 + Refined Finding 1: Per-chunk success tracking
            batch_success = True
            for chunk in chunks:
                parts = [
                    {
                        "type": "text",
                        "text": chunk.text,
                        "metadata": {
                            "chat_id": chat_id,
                            "msg_type": "transcript",
                            "chunk_id": chunk.chunk_id,
                        },
                        "time": {"start": chunk.range_start},
                    }
                ]
                try:
                    self.client.prompt_async(
                        session_uuid, parts, chunk.chunk_id, directory=directory
                    )
                    # [FIX] Refined Finding 1: Advance watermark immediately upon chunk success
                    if chunk.metadata and "last_msg_ts" in chunk.metadata:
                        last_sync_ts = chunk.metadata["last_msg_ts"]
                        last_sync_msg_id = chunk.metadata.get("last_msg_id", "")
                        last_sync_seq = int(chunk.metadata.get("last_msg_seq") or 0)
                        self._update_last_sync_time(
                            chat_id, last_sync_ts, last_sync_msg_id, last_sync_seq
                        )
                except Exception as e:
                    logger.warning(
                        f"[BRIDGE] Aggregated sync failed for {chunk.chunk_id}: {e}"
                    )
                    batch_success = False
                    # Stop batch processing if a chunk fails to avoid out-of-order retries
                    break

            if not batch_success:
                logger.error(
                    f"[BRIDGE] Sync stalled for {chat_id} due to API failure. Watermark: {last_sync_ts}"
                )
                break

            if len(batch_history) < 300:
                break

        # 2. Add Hot Context
        hot_history = self._get_hot_context(chat_id, last_sync_ts)
        for h in hot_history:
            # SDK Alignment: Structured Metadata and unix seconds
            ts_val = h.get("timestamp", "")
            try:
                # [FIX] Refined Finding 1: Use Beijing timezone for hot context
                dt = self._parse_ts(ts_val)
                unix_ts = int(dt.replace(tzinfo=BEIJING_TZ).timestamp())
            except Exception:
                unix_ts = int(time.time())

            parts = [
                {
                    "type": "text",
                    "text": f"[{ts_val}] {h['sender_name']}: {h['content']}",
                    "metadata": {
                        "chat_id": chat_id,
                        "sender_id": h.get("sender_id"),
                        "sender_name": h.get("sender_name"),
                        "msg_type": h.get("message_type", "text"),
                    },
                    "time": {"start": unix_ts},
                }
            ]
            try:
                self.client.prompt_async(
                    session_uuid,
                    parts,
                    h.get("wecom_msg_id", f"hot_{unix_ts}"),
                    directory=directory,
                )
                if ts_val > last_sync_ts:
                    last_sync_ts = ts_val
                    last_sync_msg_id = h.get("wecom_msg_id") or last_sync_msg_id
            except Exception:
                pass

        # [FIX] High/Medium Finding: Persist last_sync_ts immediately after hot messages
        self._update_last_sync_time(
            chat_id, last_sync_ts, last_sync_msg_id, last_sync_seq
        )

        # 3. Build Trigger Prompt
        active_text = msg.text or ""
        if msg.msg_type in ["file", "image", "mixed"] and msg.file:
            active_text += (
                f"\n[Active File: {msg.file.filename} (key: {msg.file.storage_key})]"
            )

        trigger_parts = [
            {
                "type": "text",
                "text": active_text,
                "metadata": {
                    "chat_id": chat_id,
                    "sender_id": msg.user_id,
                    "sender_name": msg.user_name,
                    "msg_type": msg.msg_type,
                },
                "time": {
                    "start": int(msg.msg_time / 1000)
                    if msg.msg_time > 1e12
                    else int(msg.msg_time)
                },
            }
        ]

        # 4. Stream response from OpenCode
        try:
            for event in self.client.stream_interactive(
                session_uuid, trigger_parts, msg_id, directory=directory
            ):
                yield event

        except Exception as e:
            logger.error(f"[BRIDGE] OpenCode streaming failed: {e}")
            yield {"type": "error", "content": str(e)}
