from __future__ import annotations

import logging
import time

from src.crewai_enterprise.utils.storage_manager import get_storage_manager

logger = logging.getLogger(__name__)

def _format_chat_history(history: list[dict]) -> str:
    """Formats merged chat history for LLM prompt."""
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
        
        lines.append(f"[{time_str}] {role_label}{sender}: {content}")
    
    return "\n".join(lines)




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



