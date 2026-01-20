from __future__ import annotations

import json
import logging
import time

from src.crewai_enterprise.utils.file_content_store import FileContentStore
from src.crewai_enterprise.utils.storage_manager import get_storage_manager

logger = logging.getLogger(__name__)

def _format_chat_history(history: list[dict]) -> str:
    """Formats merged chat history for LLM prompt."""
    store = FileContentStore()
    lines = []
    for msg in history:
        time_str = msg.get("timestamp", "")
        if " " in time_str:
            time_str = time_str.split(" ")[1][:5]
        else:
            time_str = time_str[:5]
        
        sender = msg.get("sender", "未知")
        content = msg.get("content", "")
        role_label = ""
        if msg.get("role") == "assistant":
            role_label = "[Bot]"

        file_hash, filename = _extract_file_payload(msg, content)
        if file_hash or msg.get("message_type") == "file" or content.startswith("[File:"):
            record = None
            if file_hash:
                record = store.get_by_hash(file_hash)
            if not record:
                msg_id = msg.get("wecom_msg_id") or msg.get("msgid")
                if msg_id:
                    record = store.get_by_msg_id(msg_id)

            display_name = filename or _extract_placeholder_filename(content) or "unknown"
            lines.append(f"[{time_str}] {role_label}{sender}: [File: {display_name}]")

            if record and record.extracted_text:
                snippet = record.extracted_text[:5000]
                suffix = "..." if len(record.extracted_text) > 5000 else ""
                lines.append(f"[File Content] {snippet}{suffix}")
            else:
                lines.append("[File Content] (not available)")
            continue
        
        lines.append(f"[{time_str}] {role_label}{sender}: {content}")
    
    return "\n".join(lines)


def _extract_file_payload(msg: dict, content: str) -> tuple[str | None, str | None]:
    if msg.get("message_type") == "file" and content.strip().startswith("{"):
        try:
            data = json.loads(content)
            if "filename" in data and "uri" in data:
                return data.get("hash"), data.get("filename")
        except Exception:
            return None, None
    return None, None


def _extract_placeholder_filename(content: str) -> str | None:
    if content.startswith("[File:"):
        trimmed = content[len("[File:"):].strip()
        if trimmed.endswith("]"):
            trimmed = trimmed[:-1].strip()
        return trimmed or None
    return None




def _upload_image_to_ucs(image_bytes: bytes) -> tuple[str | None, str | None, str, str]:
    """Upload image to cloud storage and detect correct MIME type/extension.
    
    Returns: (cloud_url, storage_key, mime_type, filename)
    """
    mime_type = "image/jpeg"
    ext = ".jpg"
    
    if image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        mime_type = "image/png"
        ext = ".png"
    elif image_bytes.startswith(b'GIF8'):
        mime_type = "image/gif"
        ext = ".gif"
    elif image_bytes.startswith(b'\x42\x4d'):
        mime_type = "image/bmp"
        ext = ".bmp"
    elif image_bytes.startswith(b'\xff\xd8\xff'):
        mime_type = "image/jpeg"
        ext = ".jpg"
        
    filename = f"upload_{int(time.time())}{ext}"
    cloud_url = None
    storage_key = None
    
    try:
        storage = get_storage_manager()
        upload_res = storage.upload_file(image_bytes, filename, content_type=mime_type)
        cloud_url = upload_res.url
        storage_key = upload_res.key
        logger.info(f"[AIBOT_UCS] Uploaded image to cloud: {cloud_url} ({mime_type}, key={storage_key})")
    except Exception as e:
        logger.error(f"[AIBOT_UCS] Cloud upload failed: {e}")
        
    return cloud_url, storage_key, mime_type, filename



