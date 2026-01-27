import sqlite3
import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from .models.opencode import WeComInbound, FileMeta

logger = logging.getLogger(__name__)

class ArchiveReader:
    def __init__(self, history_db_path: str, storage_db_path: str):
        self.history_db_path = history_db_path
        self.storage_db_path = storage_db_path

    def _get_conn(self, path: str):
        return sqlite3.connect(path)

    def fetch_recent_messages(self, chat_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch recent messages for a specific chat_id."""
        query = """
            SELECT msgid as msg_id, room_id as chat_id, sender_id as user_id, 
                   sender_id as user_name, created_at, msgtype as msg_type, content
            FROM archived_messages
            WHERE room_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """
        messages = []
        try:
            with self._get_conn(self.history_db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(query, (chat_id, limit))
                rows = cursor.fetchall()
                # Reverse to maintain temporal order for the AI
                for row in reversed(rows):
                    msg_dict = dict(row)
                    # Try to extract a better user_name from the JSON content if available
                    try:
                        c_str = msg_dict.get("content", "{}")
                        content_json = json.loads(c_str)
                        
                        # WeCom finance SDK formats vary by message type
                        # Priority: Member Name in Room > General Display Name > Sender Field
                        pref_name = (
                            content_json.get("from_chatroom_member_name") or 
                            content_json.get("from_name") or 
                            content_json.get("display_name")
                        )
                        if pref_name:
                            msg_dict["user_name"] = pref_name
                    except Exception:
                        pass
                    messages.append(msg_dict)
        except Exception as e:
            logger.error(f"Failed to fetch history for {chat_id}: {e}")
        return messages

    def fetch_ocr_content(self, msg_id: str) -> Optional[str]:
        """Fetch extracted text for a specific message from storage db."""
        query = """
            SELECT extracted_text 
            FROM file_contents 
            WHERE wecom_msg_id = ? AND status IN ('extracted', 'partial')
        """
        try:
            with self._get_conn(self.storage_db_path) as conn:
                cursor = conn.execute(query, (msg_id,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to fetch OCR for {msg_id}: {e}")
        return None

    def get_context_block(self, chat_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Build a consolidated context list for OpenCode injection."""
        history = self.fetch_recent_messages(chat_id, limit)
        context = []
        
        for msg in history:
            text = msg.get("content") or ""
            
            # If it's an image/file, try to get OCR text
            if msg.get("msg_type") in ["image", "file"]:
                ocr_text = self.fetch_ocr_content(msg["msg_id"])
                if ocr_text:
                    text += f"\n[Extracted Text: {ocr_text}]"
            
            context.append({
                "msg_id": msg["msg_id"],
                "sender": msg["user_name"],
                "time": msg["created_at"],
                "text": text
            })
        return context
